"""Assign Change Activator visibility and reload persistence."""

from __future__ import annotations

import re
import time

from playwright.async_api import Error as PlaywrightError, Locator, Page

from Backend.helpers import (
    ActionReport,
    CandidateResult,
    Outcome,
    _CandidateError,
    _new_report,
)
from Backend.config import Settings
from Backend.helpers import (
    _add_root_condition,
    _canonical,
    _click,
    _click_option,
    _close_visibility,
    _groups_named,
    _one,
    _open_activation_qa_details,
    _record_container,
    _visible,
    _wait_until,
)


# 2. Semantic controls and state checks.
async def _open_change_request_details(page: Page, timeout_ms: int) -> None:
    await _open_activation_qa_details(page, timeout_ms)
    requests = _record_container(page).get_by_test_id(
        "page-element:queryContainer"
    ).filter(has=page.get_by_role("heading", name="Change Requests", exact=True))
    # 8. Select the inner list, rather than its containing Change Requests group.
    await _click(
        page,
        requests.get_by_test_id("page-element:levels").locator(
            ':scope > div > div > [role="button"][aria-label="Select element"]'
        ),
        "Change Requests inner list",
        timeout_ms,
    )
    sidebar = page.get_by_test_id("page-creator-sidebar")
    await _click(
        page,
        sidebar.get_by_role(
            "button", name="Configure: Record detail pages", exact=True
        ),
        "Change Requests record detail pages configuration",
        timeout_ms,
    )
    await _click(
        page,
        page.get_by_test_id("popover:Record detail pages").get_by_role(
            "button",
            name="Customize Flow Core Change Request Details page",
            exact=True,
        ),
        "Flow Core Change Request Details page",
        timeout_ms,
    )
    await _one(
        page,
        _groups_named(page, "Select Activator for Change Request"),
        "Change Request Details canvas",
        timeout_ms,
        enabled=False,
    )


async def _open_assign_change_visibility(page: Page, timeout_ms: int) -> Locator:
    dialog = page.get_by_test_id("popover:Filter")
    if await _visible(dialog):
        await _close_visibility(page, dialog, timeout_ms)
    group = _groups_named(page, "Select Activator for Change Request")
    await _one(page, group, "Select Activator for Change Request group", timeout_ms)
    if await group.get_attribute("data-testid") != "selectedPageElement":
        # 9. Its center can hit a nested button. The group's own visibility marker
        # bubbles a normal click to the inspected outer selection control.
        marker = group.locator(
            ':scope > div > span > '
            '[data-testid="cell-editor-record-details-conditional-visibility-icon"]'
        )
        await _click(
            page, marker, "Select Activator for Change Request group marker", timeout_ms
        )
        await _wait_until(
            page,
            lambda: _visible(group.and_(page.get_by_test_id("selectedPageElement"))),
            "Change Request outer group selection",
            timeout_ms,
        )
    # 10. The inspected click selects the editor wrapper around the disabled action.
    button = group.locator(
        '[data-testid="call-to-action-container"] [data-cta-button]:has('
        '[role="button"][aria-label="Assign Change Activator"]'
        ') > [role="button"][aria-label="Select element"]'
    )
    await _click(page, button, "Assign Change Activator editor wrapper", timeout_ms)
    await _wait_until(
        page,
        lambda: _visible(button.and_(page.get_by_test_id("selectedPageElement"))),
        "Assign Change Activator button selection",
        timeout_ms,
    )
    await _click(
        page,
        page.get_by_test_id("page-creator-sidebar").get_by_role(
            "button", name="open Visibility popover", exact=True
        ),
        "Assign Change Activator Visibility",
        timeout_ms,
    )
    return await _one(page, dialog, "Assign Change Activator visibility filter", timeout_ms)


async def _assign_change_visibility_is_correct(dialog: Locator) -> bool:
    rows = dialog.locator("[data-filterid][aria-label]")
    if await rows.count() != 1 or await dialog.locator(
        '[aria-label*="a nested condition group"]'
    ).count():
        return False
    label = _canonical(await rows.get_attribute("aria-label") or "")
    return re.fullmatch(r"(?:Where )?1: Assign Activation is not empty", label) is not None


async def _apply_assign_change_visibility(page: Page, timeout_ms: int) -> bool:
    dialog = await _open_assign_change_visibility(page, timeout_ms)
    if await _assign_change_visibility_is_correct(dialog):
        return False
    rows = dialog.locator("[data-filterid][aria-label]")
    if await dialog.locator('[aria-label*="a nested condition group"]').count():
        raise _CandidateError("Unexpected nested visibility group; refusing to replace it.")
    count = await rows.count()
    if count == 0:
        await _add_root_condition(page, dialog, timeout_ms)
    elif count != 1 or re.fullmatch(
        r"(?:Where )?1: (?:Name|Assign Activation) contains an unset filter value",
        _canonical(await rows.get_attribute("aria-label") or "") if count == 1 else "",
    ) is None:
        raise _CandidateError(
            "Unexpected Assign Change Activator visibility; expected no conditions, "
            "the final rule, or one unfinished inspected condition."
        )
    row = await _one(page, rows, "single Assign Change Activator condition", timeout_ms)
    name = row.get_by_test_id("autocomplete-button").filter(has_text=re.compile(r"^Name$"))
    if await _visible(name):
        await _click(page, name, "visibility condition field", timeout_ms)
        await _click_option(page, "Assign Activation", timeout_ms)
    await _click(
        page,
        row.get_by_test_id("autocomplete-button").filter(has_text=re.compile(r"^contains$")),
        "Assign Activation operator",
        timeout_ms,
    )
    await _click_option(page, "is not empty", timeout_ms)
    await _wait_until(
        page,
        lambda: _assign_change_visibility_is_correct(dialog),
        "Assign Activation is not empty visibility condition",
        timeout_ms,
    )
    return True


async def _wait_for_assign_change_save(page: Page, timeout_ms: int) -> None:
    # 11. Unpublished changes describe publication, not completion of the save.
    saved = page.get_by_test_id("appTopbar").get_by_text("All changes saved", exact=True)
    saved_since: float | None = None

    async def settled() -> bool:
        nonlocal saved_since
        if not await _visible(saved):
            saved_since = None
            return False
        if saved_since is None:
            saved_since = time.monotonic()
        return time.monotonic() - saved_since >= 1

    await _wait_until(page, settled, "All changes saved before reload", timeout_ms)

# 3. Workflow entry point.
async def Assign_Change_Activator(page: Page, settings: Settings) -> ActionReport:
    action_name = 'Assign_Change_Activator'
    report = _new_report(action_name, page)
    timeout_ms = settings.browser_timeout_ms
    candidate = "Assign Change Activator visibility"
    stage = "navigation"
    try:
        await _open_change_request_details(page, timeout_ms)
        stage = "visibility condition"
        changed = await _apply_assign_change_visibility(page, timeout_ms)
        await _close_visibility(page, page.get_by_test_id("popover:Filter"), timeout_ms)
        if changed:
            stage = "save"
            await _wait_for_assign_change_save(page, timeout_ms)
        stage = "reload persistence"
        await page.reload(wait_until="domcontentloaded")
        # 12. Airtable drops a details URL with a null record on reload.
        await _open_change_request_details(page, timeout_ms)
        dialog = await _open_assign_change_visibility(page, timeout_ms)
        await _wait_until(
            page,
            lambda: _assign_change_visibility_is_correct(dialog),
            "Assign Activation is not empty to persist after reload",
            timeout_ms,
        )
        await _close_visibility(page, dialog, timeout_ms)
        report.results.append(CandidateResult(
            candidate=candidate,
            outcome=Outcome.SUCCESS if changed else Outcome.SKIPPED,
            message=("Applied" if changed else "Already correct; skipped")
            + " Assign Activation is not empty; verified after reload.",
        ))
    except (_CandidateError, PlaywrightError) as exc:
        report.results.append(CandidateResult(
            candidate=candidate,
            outcome=Outcome.FAILED,
            message=str(exc),
            details={"stage": stage, "stage_url": page.url},
        ))
    return report.finish(page)

