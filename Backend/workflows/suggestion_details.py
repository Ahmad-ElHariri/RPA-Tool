"""Suggestion Details visibility in the two inspected media-plan views."""

from __future__ import annotations

import re

from playwright.async_api import Error as PlaywrightError, Locator, Page

from Backend.helpers import ActionReport, _CandidateError, _new_report
from Backend.config import Settings
from Backend.helpers import (
    _click,
    _one,
    _run_validated_section,
    _validation_only,
    _wait_for_interface_save,
    _workflow_failure,
)


# 1. Workflow constants.
_SUGGESTION_DETAILS = "Suggestion Details"
_SUGGESTION_DETAIL_SECTIONS = (
    ("Add/Edit Media Plans", "page-element:grid"),
    ("Review Media Plans", "page-element:levels"),
)

# 2. Semantic controls and state checks.
async def _wait_for_brief_detail_sections(page: Page, timeout_ms: int) -> None:
    for section_name, _ in _SUGGESTION_DETAIL_SECTIONS:
        heading = page.get_by_role(
            "heading", name=section_name, exact=True
        )
        await heading.scroll_into_view_if_needed(timeout=timeout_ms)


def _visualization_selection_control(visualization: Locator) -> Locator:
    return visualization.locator(
        ':scope > div > div > [role="button"][aria-label="Select element"]'
    )


async def _open_flow_core_brief_details(
    page: Page, timeout_ms: int
) -> None:
    topbar = page.locator('header[data-testid="appTopbar"]')
    await _one(page, topbar, "Airtable top bar", timeout_ms, enabled=False)
    await _click(
        page,
        topbar.get_by_role("link", name="Interfaces", exact=True),
        "Interfaces link",
        timeout_ms,
    )
    navigation = page.get_by_test_id("PageNavigationLeftNav")
    await _click(
        page,
        navigation.get_by_role("link", name="Flow Core", exact=True),
        "Flow Core interface",
        timeout_ms,
    )

    planning_list = page.get_by_test_id("page-element:levels")
    populated_list = _visualization_selection_control(planning_list)
    empty_list = planning_list.locator(":scope > div").filter(
        has_text=re.compile(
            r"^\s*No briefs found that match current filters\s*"
            r"Remove filters to see more results\s*$"
        )
    )
    await _click(
        page,
        populated_list.or_(empty_list),
        "Flow Core Planning list",
        timeout_ms,
    )
    await _click(
        page,
        page.get_by_role(
            "button", name="Configure: Record detail pages", exact=True
        ),
        "Record detail pages configuration",
        timeout_ms,
    )
    detail_pages = page.get_by_test_id("popover:Record detail pages")
    await _click(
        page,
        detail_pages.get_by_role(
            "button",
            name="Customize Flow Core - Brief Details page",
            exact=True,
        ),
        "Flow Core - Brief Details page",
        timeout_ms,
    )
    await _wait_for_brief_detail_sections(page, timeout_ms)


async def _open_suggestion_details_fields(
    page: Page,
    section_name: str,
    visualization_test_id: str,
    timeout_ms: int,
) -> Locator:
    heading = page.get_by_role("heading", name=section_name, exact=True)
    await heading.scroll_into_view_if_needed(timeout=timeout_ms)
    section = page.get_by_test_id("page-element:queryContainer").filter(
        has=heading
    )
    visualization = section.get_by_test_id(visualization_test_id)
    await _click(
        page,
        _visualization_selection_control(visualization),
        f"{section_name!r} data visualization",
        timeout_ms,
    )
    sidebar = page.get_by_test_id("page-creator-sidebar")
    await _click(
        page,
        sidebar.get_by_role(
            "button", name="open Fields popover", exact=True
        ),
        f"{section_name!r} Fields setting",
        timeout_ms,
    )
    dialog = await _one(
        page,
        page.get_by_test_id("popover:Fields"),
        f"{section_name!r} Fields dialog",
        timeout_ms,
        enabled=False,
    )
    search = await _one(
        page,
        dialog.get_by_role("textbox"),
        f"{section_name!r} Fields search",
        timeout_ms,
    )
    await search.fill(_SUGGESTION_DETAILS.casefold(), timeout=timeout_ms)
    return dialog


async def _suggestion_details_state(
    page: Page, dialog: Locator, section_name: str, timeout_ms: int
) -> tuple[str, Locator]:
    field_control = dialog.get_by_role(
        "button", name=_SUGGESTION_DETAILS, exact=True
    )
    await field_control.scroll_into_view_if_needed(timeout=timeout_ms)
    field_control = await _one(
        page,
        field_control,
        f"Suggestion Details row control in {section_name!r}",
        timeout_ms,
    )
    await field_control.click(timeout=timeout_ms)
    await page.wait_for_timeout(100)
    hide = dialog.locator(
        f'[role="button"][aria-label="Hide {_SUGGESTION_DETAILS}"]'
    )
    show = dialog.locator(
        f'[role="button"][aria-label="Show {_SUGGESTION_DETAILS}"]'
    )
    counts = (await hide.count(), await show.count())
    if counts == (1, 0):
        return "visible", hide
    if counts == (0, 1):
        return "hidden", show
    raise _CandidateError(
        f"Could not determine Suggestion Details visibility in "
        f"{section_name!r}: found {counts[0]} Hide controls and "
        f"{counts[1]} Show controls."
    )


async def _ensure_suggestion_details_hidden(
    page: Page,
    section_name: str,
    visualization_test_id: str,
    timeout_ms: int,
) -> bool:
    dialog = await _open_suggestion_details_fields(
        page, section_name, visualization_test_id, timeout_ms
    )
    state, visibility_control = await _suggestion_details_state(
        page, dialog, section_name, timeout_ms
    )
    if state == "hidden":
        return False

    await _click(
        page,
        visibility_control,
        f"Hide Suggestion Details in {section_name!r}",
        timeout_ms,
    )
    return True


async def _suggestion_details_is_hidden(
    page: Page,
    section_name: str,
    visualization_test_id: str,
    timeout_ms: int,
) -> bool:
    dialog = await _open_suggestion_details_fields(
        page, section_name, visualization_test_id, timeout_ms
    )
    state, _ = await _suggestion_details_state(
        page, dialog, section_name, timeout_ms
    )
    return state == "hidden"

# 3. Workflow entry point.
async def hide_suggestion_details(page: Page, settings: Settings) -> ActionReport:
    """Hide Suggestion Details in both inspected Brief Details sections."""
    action_name = 'hide_suggestion_details'
    report = _new_report(action_name, page)
    timeout_ms = settings.browser_timeout_ms
    sections = dict(_SUGGESTION_DETAIL_SECTIONS)
    section_names = tuple(sections)
    try:
        await _open_flow_core_brief_details(page, timeout_ms)
        complete = await _run_validated_section(
            page,
            report,
            "Suggestion Details field",
            section_names,
            lambda name: _ensure_suggestion_details_hidden(
                page, name, sections[name], timeout_ms
            ),
            lambda name: _suggestion_details_is_hidden(
                page, name, sections[name], timeout_ms
            ),
            timeout_ms,
            save_waiter=_wait_for_interface_save,
        )
        if not complete:
            return report.finish(page)

        await page.reload(wait_until="domcontentloaded")
        await _wait_for_brief_detail_sections(page, timeout_ms)
        await _run_validated_section(
            page,
            report,
            "Suggestion Details reload persistence",
            section_names,
            lambda _: _validation_only(),
            lambda name: _suggestion_details_is_hidden(
                page, name, sections[name], timeout_ms
            ),
            timeout_ms,
            retries=0,
        )
    except (_CandidateError, PlaywrightError) as exc:
        _workflow_failure(page, report, 'Flow Core Suggestion Details workflow', exc)
    return report.finish(page)

