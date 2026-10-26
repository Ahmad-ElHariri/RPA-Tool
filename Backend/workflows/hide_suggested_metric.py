"""Workflow: hide_suggested_metric. Task steps and private controls."""

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
    _run_core_validated_section,
)


_MEDIA_PLAN_SECTIONS = (
    ("Add/Edit Media Plans", "page-element:grid"),
    ("Review Media Plans", "page-element:levels"),
)


_SUGGESTED_METRIC = "Suggested Metric"


async def _open_flow_core_planning(page: Page, timeout_ms: int) -> bool:
    """Open Flow Core Planning and select its list visualization."""
    await page.locator('header[data-testid="appTopbar"]').wait_for(
        timeout=timeout_ms
    )
    await page.wait_for_timeout(1_000)
    navigation = page.get_by_test_id("PageNavigationLeftNav")
    flow_core = navigation.get_by_role("link", name="Flow Core", exact=True)
    await _require_one(
        page,
        flow_core,
        "Flow Core navigation link",
        timeout_ms,
        exact_text="Flow Core",
    )
    await flow_core.click()
    levels = page.get_by_test_id("page-element:levels")
    empty_state = levels.locator(":scope > div").filter(
        has_text=re.compile(
            r"^\s*No briefs found that match current filters\s*"
            r"Remove filters to see more results\s*$"
        )
    )
    await _require_one(
        page,
        empty_state,
        "Flow Core Planning list canvas",
        timeout_ms,
        exact_text=(
            "No briefs found that match current filters "
            "Remove filters to see more results"
        ),
    )
    await empty_state.click()
    return True


async def _planning_list_is_selected(page: Page, timeout_ms: int) -> bool:
    await _require_one(
        page,
        page.get_by_role(
            "button", name="Configure: Record detail pages", exact=True
        ),
        "Planning Record detail pages configuration button",
        timeout_ms,
    )
    return True


async def _open_flow_core_brief_details(page: Page, timeout_ms: int) -> bool:
    configure = await _require_one(
        page,
        page.get_by_role(
            "button", name="Configure: Record detail pages", exact=True
        ),
        "Planning Record detail pages configuration button",
        timeout_ms,
    )
    await configure.click()
    dialog = page.get_by_test_id("popover:Record detail pages")
    customize = await _require_one(
        page,
        dialog.get_by_role(
            "button",
            name="Customize Flow Core - Brief Details page",
            exact=True,
        ),
        "Flow Core - Brief Details customize button",
        timeout_ms,
    )
    await customize.click()
    await page.wait_for_timeout(1_500)
    return True


async def _brief_details_is_open(page: Page, timeout_ms: int) -> bool:
    for section_name, _ in _MEDIA_PLAN_SECTIONS:
        heading = page.get_by_role("heading", name=section_name, exact=True)
        await heading.scroll_into_view_if_needed(timeout=timeout_ms)
        await _require_one(
            page,
            heading,
            f"{section_name!r} section heading",
            timeout_ms,
            exact_text=section_name,
        )
    return True


async def _close_fields_popover(page: Page, timeout_ms: int) -> None:
    dialog = page.get_by_test_id("popover:Fields")
    for handle in await dialog.element_handles():
        if not await handle.is_visible():
            continue
        close = await _require_one(
            page,
            dialog.get_by_role("button", name="Close", exact=True),
            "Fields popover Close button",
            timeout_ms,
        )
        await close.click()
        return


async def _open_media_plan_fields(
    page: Page,
    section_name: str,
    visualization_test_id: str,
    timeout_ms: int,
) -> Locator:
    """Select one named visualization and filter its Fields popover."""
    await _close_fields_popover(page, timeout_ms)
    section = page.get_by_test_id("page-element:queryContainer").filter(
        has=page.get_by_role("heading", name=section_name, exact=True)
    )
    await section.scroll_into_view_if_needed(timeout=timeout_ms)
    selection_locator = section.get_by_test_id(
        visualization_test_id
    ).get_by_role("button", name="Select element", exact=True)
    await selection_locator.scroll_into_view_if_needed(timeout=timeout_ms)
    selection = await _require_one(
        page,
        selection_locator,
        f"{section_name!r} data visualization selection control",
        timeout_ms,
    )
    await selection.click()

    sidebar = page.get_by_test_id("page-creator-sidebar")
    fields_button = await _require_one(
        page,
        sidebar.get_by_role("button", name="open Fields popover", exact=True),
        f"{section_name!r} Fields settings button",
        timeout_ms,
    )
    await fields_button.click()
    dialog = page.get_by_test_id("popover:Fields")
    search = await _require_one(
        page,
        dialog.get_by_role("textbox"),
        f"{section_name!r} Fields search input",
        timeout_ms,
    )
    await search.fill(_SUGGESTED_METRIC.casefold())
    return dialog


async def _suggested_metric_state(
    page: Page, dialog: Locator, section_name: str, timeout_ms: int
) -> tuple[str, Locator]:
    row = dialog.get_by_role("listitem").filter(
        has_text=re.compile(r"^\s*Suggested Metric\s*$")
    )
    await _require_one(
        page,
        row,
        f"exact Suggested Metric field row in {section_name!r}",
        timeout_ms,
        exact_text=_SUGGESTED_METRIC,
    )
    await row.hover()
    await page.wait_for_timeout(100)
    hide = row.get_by_role(
        "button", name=f"Hide {_SUGGESTED_METRIC}", exact=True
    )
    show = row.get_by_role(
        "button", name=f"Show {_SUGGESTED_METRIC}", exact=True
    )
    hide_count, show_count = await hide.count(), await show.count()
    if (hide_count, show_count) == (1, 0):
        return "visible", row
    if (hide_count, show_count) == (0, 1):
        return "hidden", row
    raise _CandidateError(
        f"Could not determine Suggested Metric visibility in {section_name!r}: "
        f"found {hide_count} Hide controls and {show_count} Show controls."
    )


async def _ensure_suggested_metric_hidden(
    page: Page,
    section_name: str,
    visualization_test_id: str,
    timeout_ms: int,
) -> bool:
    dialog = await _open_media_plan_fields(
        page, section_name, visualization_test_id, timeout_ms
    )
    state, row = await _suggested_metric_state(
        page, dialog, section_name, timeout_ms
    )
    if state == "hidden":
        return False
    await row.hover()
    hide = await _require_one(
        page,
        row.get_by_role(
            "button", name=f"Hide {_SUGGESTED_METRIC}", exact=True
        ),
        f"Hide Suggested Metric control in {section_name!r}",
        timeout_ms,
    )
    await hide.click()
    return True


async def _suggested_metric_is_hidden(
    page: Page,
    section_name: str,
    visualization_test_id: str,
    timeout_ms: int,
) -> bool:
    dialog = await _open_media_plan_fields(
        page, section_name, visualization_test_id, timeout_ms
    )
    state, _ = await _suggested_metric_state(
        page, dialog, section_name, timeout_ms
    )
    return state == "hidden"


async def hide_suggested_metric(page: Page, settings: Settings) -> ActionReport:
    """Hide Suggested Metric in both Flow Core Brief Details media-plan grids."""
    action_name = "hide_suggested_metric"
    report = _new_report(action_name, page)
    timeout_ms = settings.browser_timeout_ms

    try:
        if not await _run_core_validated_section(
            page,
            report,
            "Flow Core Planning navigation",
            ("Planning list",),
            lambda _: _open_flow_core_planning(page, timeout_ms),
            lambda _: _planning_list_is_selected(page, timeout_ms),
            timeout_ms,
        ):
            return report.finish(page)

        if not await _run_core_validated_section(
            page,
            report,
            "Brief Details navigation",
            ("Flow Core - Brief Details",),
            lambda _: _open_flow_core_brief_details(page, timeout_ms),
            lambda _: _brief_details_is_open(page, timeout_ms),
            timeout_ms,
        ):
            return report.finish(page)

        section_test_ids = dict(_MEDIA_PLAN_SECTIONS)
        section_names = tuple(section_test_ids)
        if not await _run_core_validated_section(
            page,
            report,
            "Suggested Metric field",
            section_names,
            lambda name: _ensure_suggested_metric_hidden(
                page, name, section_test_ids[name], timeout_ms
            ),
            lambda name: _suggested_metric_is_hidden(
                page, name, section_test_ids[name], timeout_ms
            ),
            timeout_ms,
        ):
            return report.finish(page)

        await _close_fields_popover(page, timeout_ms)
        await page.reload(wait_until="domcontentloaded")
        await _brief_details_is_open(page, timeout_ms)
        await _run_core_validated_section(
            page,
            report,
            "Reload persistence",
            section_names,
            lambda _: _unchanged(),
            lambda name: _suggested_metric_is_hidden(
                page, name, section_test_ids[name], timeout_ms
            ),
            timeout_ms,
        )
    except (_CandidateError, PlaywrightError) as exc:
        report.results.append(
            CandidateResult(
                candidate="Flow Core Suggested Metric workflow",
                outcome=Outcome.FAILED,
                message=str(exc),
                details={"stage_url": page.url},
            )
        )

    return report.finish(page)


async def _unchanged() -> bool:
    """Represent a validation-only item in the shared section runner."""
    return False
