"""Visibility configuration for the inspected Activation QA fields."""

from __future__ import annotations

import re

from playwright.async_api import Error as PlaywrightError, Locator, Page

from Backend.helpers import ActionReport, _CandidateError, _new_report
from Backend.config import Settings
from Backend.helpers import (
    _canonical,
    _click,
    _click_option,
    _groups_named,
    _one,
    _open_activation_qa_details,
    _run_validated_section,
    _validation_only,
    _wait_for_interface_save,
    _wait_until,
    _workflow_failure,
)


# 1. Workflow constants.
_ACTIVATION_QA_FIELDS = (
    "2nd Check - Media Plan & Booking Alignment",
    "2nd Check - Platform Setup QA",
    "2nd Check - Creative & Placement QA",
    "2nd Check - Tracking & Measurement QA",
)
_ACTIVATION_QA_FIELD_ALIASES = {
    _ACTIVATION_QA_FIELDS[0]: (
        _ACTIVATION_QA_FIELDS[0],
        "2nd Check - Media Booking System",
    ),
    _ACTIVATION_QA_FIELDS[1]: (
        _ACTIVATION_QA_FIELDS[1],
        "2nd Check - Trafficking Workbook",
    ),
    _ACTIVATION_QA_FIELDS[2]: (
        _ACTIVATION_QA_FIELDS[2],
        "2nd Check - Creative Matrix",
    ),
    _ACTIVATION_QA_FIELDS[3]: (
        _ACTIVATION_QA_FIELDS[3],
        "2nd Check - Tracking Partners",
    ),
}
_ACTIVATION_QA_VISIBILITY_VALUE = "xzx"

# 2. Semantic controls and state checks.
async def _resolve_activation_qa_cell(
    page: Page, field_name: str, timeout_ms: int
) -> tuple[Locator, str]:
    aliases = _ACTIVATION_QA_FIELD_ALIASES[field_name]
    label_pattern = re.compile(
        rf"^(?:{'|'.join(re.escape(alias) for alias in aliases)})$"
    )
    label = page.get_by_test_id("page-element-label").filter(
        has_text=label_pattern
    )
    qa_controls = page.locator(
        '[data-testid="call-to-action-container"] [data-cta-button]'
    )
    checklist = _groups_named(page, "Activator Check List").filter(
        has_not=qa_controls
    )
    checklist = await _one(
        page,
        checklist,
        "Activator Check List group without QA buttons",
        timeout_ms,
        enabled=False,
    )
    cell = checklist.locator(
        '[data-testid="page-element:cellEditor"]:visible'
    ).filter(has=label)
    cell = await _one(
        page,
        cell,
        f"{field_name!r} check using labels {aliases!r}",
        timeout_ms,
    )
    actual_name = _canonical(
        await cell.get_by_test_id("page-element-label").inner_text()
    )
    return cell, actual_name


async def _open_activation_qa_visibility(
    page: Page, field_name: str, timeout_ms: int
) -> Locator:
    cell, actual_name = await _resolve_activation_qa_cell(
        page, field_name, timeout_ms
    )
    await _click(
        page,
        cell.locator(
            ':scope > [role="button"][aria-label="Select element"]'
        ),
        actual_name,
        timeout_ms,
    )
    sidebar = page.get_by_test_id("page-creator-sidebar")
    await _one(
        page,
        sidebar.get_by_text(actual_name, exact=True),
        f"{actual_name!r} sidebar selection",
        timeout_ms,
        enabled=False,
    )
    await _click(
        page,
        sidebar.get_by_role(
            "button", name="open Visibility popover", exact=True
        ),
        f"{actual_name!r} Visibility setting",
        timeout_ms,
    )
    return await _one(
        page,
        page.get_by_test_id("popover:Filter"),
        f"{actual_name!r} Visibility dialog",
        timeout_ms,
    )


async def _activation_qa_condition_is_correct(row: Locator) -> bool:
    if await row.count() != 1:
        return False
    name = row.get_by_test_id("autocomplete-button").filter(
        has_text=re.compile(r"^Name$")
    )
    operator = row.get_by_test_id("autocomplete-button").filter(
        has_text=re.compile(r"^is$")
    )
    value = row.get_by_role(
        "textbox", name="Filter comparison value", exact=True
    )
    return (
        await name.count() == 1
        and await operator.count() == 1
        and await value.count() == 1
        and await value.input_value() == _ACTIVATION_QA_VISIBILITY_VALUE
    )


async def _apply_activation_qa_visibility(
    page: Page, field_name: str, timeout_ms: int
) -> bool:
    dialog = await _open_activation_qa_visibility(
        page, field_name, timeout_ms
    )
    rows = dialog.locator("[data-filterid][aria-label]")
    count = await rows.count()
    if count > 1:
        raise _CandidateError(
            f"{field_name!r} has {count} visibility conditions; expected zero "
            "or the single inspected Name condition."
        )
    if count == 1:
        row = rows
        if await _activation_qa_condition_is_correct(row):
            return False
        label = await row.get_attribute("aria-label") or ""
        canonical = _canonical(label)
        allowed = re.match(
            r"^(?:Where |and |or )?\d+(?:\.\d+)?: "
            r"Name (?:contains|is) an unset filter value$",
            canonical,
        )
        if allowed is None:
            raise _CandidateError(
                f"{field_name!r} has an unexpected visibility condition: "
                f"{canonical!r}."
            )
    else:
        await _click(
            page,
            dialog.get_by_role("button", name="Add condition", exact=True),
            f"{field_name!r} Add condition",
            timeout_ms,
        )
        row = await _one(
            page,
            rows,
            f"{field_name!r} new Name condition",
            timeout_ms,
        )
        canonical = _canonical(await row.get_attribute("aria-label") or "")

    if "Name contains an unset filter value" in canonical:
        operator = row.locator(
            '[data-testid="autocomplete-button"][role="button"]'
        ).filter(has_text=re.compile(r"^contains$"))
        await _click(page, operator, f"{field_name!r} operator", timeout_ms)
        await _click_option(page, "is...", timeout_ms)

    value = await _one(
        page,
        row.get_by_role(
            "textbox", name="Filter comparison value", exact=True
        ),
        f"{field_name!r} comparison value",
        timeout_ms,
    )
    await value.fill(_ACTIVATION_QA_VISIBILITY_VALUE, timeout=timeout_ms)
    await value.press("Tab", timeout=timeout_ms)

    async def applied() -> bool:
        return await _activation_qa_condition_is_correct(rows)

    await _wait_until(
        page,
        applied,
        f"{field_name!r} visibility to become Name is xzx",
        timeout_ms,
    )
    return True


async def _validate_activation_qa_visibility(
    page: Page, field_name: str, timeout_ms: int
) -> bool:
    dialog = await _open_activation_qa_visibility(
        page, field_name, timeout_ms
    )
    rows = dialog.locator("[data-filterid][aria-label]")
    if await rows.count() != 1:
        return False
    return await _activation_qa_condition_is_correct(rows)

# 3. Workflow entry point.
async def configure_activation_qa_visibility(page: Page, settings: Settings) -> ActionReport:
    """Add the inspected Name is xzx rule to four Activation QA fields."""
    action_name = 'configure_activation_qa_visibility'
    report = _new_report(action_name, page)
    timeout_ms = settings.browser_timeout_ms
    try:
        await _open_activation_qa_details(page, timeout_ms)
        for field_name in _ACTIVATION_QA_FIELDS:
            await _resolve_activation_qa_cell(page, field_name, timeout_ms)
        complete = await _run_validated_section(
            page,
            report,
            "Activation QA visibility",
            _ACTIVATION_QA_FIELDS,
            lambda field: _apply_activation_qa_visibility(
                page, field, timeout_ms
            ),
            lambda field: _validate_activation_qa_visibility(
                page, field, timeout_ms
            ),
            timeout_ms,
            save_waiter=_wait_for_interface_save,
        )
        if not complete:
            return report.finish(page)

        await page.reload(wait_until="domcontentloaded")
        await _one(
            page,
            page.get_by_test_id("page-element-expansion-stack-renderer-dialog"),
            "reloaded Activation Details dialog",
            timeout_ms,
            enabled=False,
        )
        await _run_validated_section(
            page,
            report,
            "Activation QA visibility reload persistence",
            _ACTIVATION_QA_FIELDS,
            lambda _: _validation_only(),
            lambda field: _validate_activation_qa_visibility(
                page, field, timeout_ms
            ),
            timeout_ms,
            retries=0,
        )
    except (_CandidateError, PlaywrightError) as exc:
        _workflow_failure(page, report, 'Activation QA visibility workflow', exc)
    return report.finish(page)

