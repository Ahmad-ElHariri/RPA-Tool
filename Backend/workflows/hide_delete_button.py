"""Workflow: hide_delete_button. Task steps and private controls."""

from __future__ import annotations

import re
from playwright.async_api import Error as PlaywrightError, Locator, Page
from Backend.config import Settings
from Backend.helpers import (
    ActionReport,
    CandidateResult,
    Outcome,
    _CandidateError,
    _new_report,
    _require_one,
    _wait_for_core_interface_save,
)


_DELETE_BUTTON_LABEL = "Delete Line Item"


_DELETE_BUTTON_SECTION = "Campaigns Sent For Activation"


_DELETE_BUTTON_FIELD = "Campaign Status"


_DELETE_BUTTON_VALUE = "Pre-Briefing"


async def _open_delete_button_settings(page: Page, timeout_ms: int) -> bool:
    """Open the recorded record-details page and select Delete Line Item."""
    await page.locator('header[data-testid="appTopbar"]').wait_for(
        timeout=timeout_ms
    )
    section_heading = page.get_by_role(
        "heading", name=_DELETE_BUTTON_SECTION, exact=True
    )
    await section_heading.scroll_into_view_if_needed(timeout=timeout_ms)
    section_selector = section_heading.locator(
        'xpath=ancestor::*[@role="button" and @aria-label="Select element"][1]'
    )
    await (await _require_one(
        page,
        section_selector,
        f"{_DELETE_BUTTON_SECTION!r} section selection control",
        timeout_ms,
    )).click()

    configure = await _require_one(
        page,
        page.get_by_role(
            "button", name="Configure: Record detail pages", exact=True
        ),
        f"{_DELETE_BUTTON_SECTION!r} Record detail pages configuration button",
        timeout_ms,
    )
    await configure.click()
    detail_pages = page.get_by_test_id("popover:Record detail pages")
    customize = detail_pages.get_by_role(
        "button", name="Customize Flow Core Planning page", exact=True
    )
    await (await _require_one(
        page,
        customize,
        f"{_DELETE_BUTTON_SECTION!r} detail-page Customize button",
        timeout_ms,
    )).click()

    delete_text = page.get_by_text(_DELETE_BUTTON_LABEL, exact=True)
    delete_button = await _require_one(
        page,
        delete_text.locator(
            'xpath=ancestor::*[@role="button" and @aria-label="Select element"][1]'
        ),
        f"{_DELETE_BUTTON_LABEL!r} button",
        timeout_ms,
        exact_text=_DELETE_BUTTON_LABEL,
    )
    await delete_button.click()
    await _require_one(
        page,
        page.get_by_test_id("page-creator-sidebar").get_by_role(
            "button", name="open Visibility popover", exact=True
        ),
        f"{_DELETE_BUTTON_LABEL!r} Visibility settings",
        timeout_ms,
    )
    return True


async def _open_delete_visibility(page: Page, timeout_ms: int) -> Locator:
    sidebar = page.get_by_test_id("page-creator-sidebar")
    opener = await _require_one(
        page,
        sidebar.get_by_role(
            "button", name="open Visibility popover", exact=True
        ),
        f"{_DELETE_BUTTON_LABEL!r} Visibility settings",
        timeout_ms,
    )
    await opener.click()
    dialog = page.get_by_test_id("popover:Filter")
    await _require_one(page, dialog, "Visibility Filter dialog", timeout_ms)
    return dialog


async def _delete_visibility_is_correct(
    page: Page, timeout_ms: int, *, close: bool = True
) -> bool:
    """Read the complete one-condition state without changing it."""
    dialog = await _open_delete_visibility(page, timeout_ms)
    prefixes = dialog.get_by_test_id("filter-prefix-label")
    correct = False
    if await prefixes.count() == 1:
        row = prefixes.locator("xpath=ancestor::*[@aria-label][1]")
        normalized = " ".join((await row.inner_text()).split())
        correct = re.fullmatch(
            rf"(?:Where )?{re.escape(_DELETE_BUTTON_FIELD)} is "
            rf"{re.escape(_DELETE_BUTTON_VALUE)}",
            normalized,
        ) is not None
    if close:
        await page.keyboard.press("Escape")
    return correct


async def _ensure_delete_visibility(page: Page, timeout_ms: int) -> bool:
    """Set the sole visibility rule, or skip when its complete state is correct."""
    dialog = await _open_delete_visibility(page, timeout_ms)
    prefixes = dialog.get_by_test_id("filter-prefix-label")
    if await prefixes.count() == 0:
        add_condition = await _require_one(
            page,
            dialog.get_by_role("button", name="Add condition", exact=True),
            "Add visibility condition button",
            timeout_ms,
        )
        await add_condition.click()
    if await prefixes.count() != 1:
        raise _CandidateError(
            "Expected exactly one Delete Line Item visibility condition."
        )
    row = prefixes.locator("xpath=ancestor::*[@aria-label][1]")
    row_text = " ".join((await row.inner_text()).split())
    if re.fullmatch(
        rf"(?:Where )?{re.escape(_DELETE_BUTTON_FIELD)} is "
        rf"{re.escape(_DELETE_BUTTON_VALUE)}",
        row_text,
    ):
        await page.keyboard.press("Escape")
        return False

    field = row.locator(
        '[data-testid="autocomplete-button"][role="button"]'
    ).filter(
        has_not_text=re.compile(
            r"^(?:contains|does not contain|is|is not|is empty|is not empty)$",
            re.IGNORECASE,
        )
    )
    await (await _require_one(
        page, field, "visibility condition field", timeout_ms
    )).click()
    field_search = await _require_one(
        page,
        page.get_by_role("combobox", name="Find a field", exact=True),
        "visibility field search",
        timeout_ms,
    )
    await field_search.fill(_DELETE_BUTTON_FIELD)
    await (await _require_one(
        page,
        page.get_by_role("option").filter(
            has_text=re.compile(rf"^{re.escape(_DELETE_BUTTON_FIELD)}$")
        ),
        f"{_DELETE_BUTTON_FIELD!r} field option",
        timeout_ms,
        exact_text=_DELETE_BUTTON_FIELD,
    )).click()

    value = await _require_one(
        page,
        dialog.get_by_role("combobox", name=_DELETE_BUTTON_FIELD, exact=True),
        f"{_DELETE_BUTTON_FIELD!r} value selector",
        timeout_ms,
    )
    await value.click()
    await (await _require_one(
        page,
        page.get_by_role("option").filter(
            has_text=re.compile(rf"^{re.escape(_DELETE_BUTTON_VALUE)}$")
        ),
        f"{_DELETE_BUTTON_VALUE!r} option",
        timeout_ms,
        exact_text=_DELETE_BUTTON_VALUE,
    )).click()
    await page.keyboard.press("Escape")
    return True


async def hide_delete_button(page: Page, settings: Settings) -> ActionReport:
    """Show Delete Line Item only when Campaign Status is Pre-Briefing."""
    action_name = "hide_delete_button"
    report = _new_report(action_name, page)
    timeout_ms = settings.browser_timeout_ms

    try:
        await _open_delete_button_settings(page, timeout_ms)
        changed = await _ensure_delete_visibility(page, timeout_ms)
        if changed:
            await _wait_for_core_interface_save(page, timeout_ms)
        correct = await _delete_visibility_is_correct(page, timeout_ms)
        if not correct:
            raise _CandidateError(
                "Delete Line Item visibility did not match Campaign Status is Pre-Briefing."
            )
        report.results.append(CandidateResult(
            candidate="Delete Line Item visibility",
            outcome=Outcome.SUCCESS if changed else Outcome.SKIPPED,
            message=(
                "Applied and validated Campaign Status is Pre-Briefing."
                if changed else
                "Campaign Status is Pre-Briefing is already configured."
            ),
        ))

        await page.reload(wait_until="domcontentloaded")
        await _open_delete_button_settings(page, timeout_ms)
        if not await _delete_visibility_is_correct(page, timeout_ms):
            raise _CandidateError(
                "Delete Line Item visibility did not persist after reload."
            )
        report.results.append(CandidateResult(
            candidate="Delete Line Item reload persistence",
            outcome=Outcome.SUCCESS,
            message="Verified the visibility condition after reload.",
        ))
    except (_CandidateError, PlaywrightError) as exc:
        report.results.append(CandidateResult(
            candidate="Delete Line Item visibility workflow",
            outcome=Outcome.FAILED,
            message=str(exc),
            details={"stage_url": page.url},
        ))

    return report.finish(page)
