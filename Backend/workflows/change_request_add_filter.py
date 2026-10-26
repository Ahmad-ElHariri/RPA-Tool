"""Workflow: change_request_add_filter. Task steps and private controls."""

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
)


_CHANGE_REQUEST_FIELD = "Status (from QA Reviews)"


_CHANGE_REQUEST_CONDITIONS = (
    (1, "is exactly", "QA Complete"),
    (2, "is empty", None),
)


_CHANGE_REQUEST_WARNING = "This view is used by automations"


async def _open_change_request_filters(page: Page, timeout_ms: int) -> None:
    opener = await _require_one(
        page,
        page.get_by_role("button", name="Filter rows", exact=True),
        "Filter rows button",
        timeout_ms,
    )
    await opener.click()
    for group_number, _, _ in _CHANGE_REQUEST_CONDITIONS:
        await _change_request_add_button(page, group_number, timeout_ms)


async def _change_request_add_button(
    page: Page, group_number: int, timeout_ms: int
) -> Locator:
    button = page.get_by_role(
        "button",
        name=f"add conditions and subgroups to condition group {group_number}",
        exact=True,
    )
    await _require_one(
        page, button, f"condition group {group_number} add button", timeout_ms
    )
    return button


def _change_request_pattern(
    group_number: int, operator: str, value: str | None
) -> re.Pattern[str]:
    tail = operator if value is None else f"{operator} {value}"
    return re.compile(
        rf"^(?:Where|and|or) {group_number}\.\d+: "
        rf"{re.escape(_CHANGE_REQUEST_FIELD)}\s+{re.escape(tail)}$",
        re.IGNORECASE,
    )


async def _change_request_condition_exists(
    page: Page, group_number: int, operator: str, value: str | None
) -> bool:
    pattern = _change_request_pattern(group_number, operator, value)
    labels = await page.locator("[aria-label]").evaluate_all(
        "elements => elements.map(element => element.getAttribute('aria-label'))"
    )
    return any(
        label and pattern.fullmatch(" ".join(label.split())) for label in labels
    )


def _blank_change_request_rows(page: Page, group_number: int) -> Locator:
    return page.locator(
        f'div[aria-label^="and {group_number}."]'
        '[aria-label$=": Name contains an unset filter value"]'
    )


async def _configure_change_request_condition(
    page: Page,
    group_number: int,
    operator: str,
    value: str | None,
    timeout_ms: int,
) -> None:
    blank_row = _blank_change_request_rows(page, group_number)
    blank_count = await blank_row.count()
    if blank_count > 1:
        raise _CandidateError(
            f"Found {blank_count} incomplete Name conditions in group "
            f"{group_number}; refusing to choose by position."
        )
    if blank_count == 0:
        add_button = await _change_request_add_button(
            page, group_number, timeout_ms
        )
        await add_button.click()
        menu_item = page.get_by_role("menu").get_by_role("menuitem").filter(
            has_text=re.compile(r"^Add condition$")
        )
        await (await _require_one(
            page,
            menu_item,
            "Add condition menu item",
            timeout_ms,
            exact_text="Add condition",
        )).click()

    blank_handle = await _require_one(
        page,
        blank_row,
        f"new incomplete Name condition in group {group_number}",
        timeout_ms,
    )
    blank_label = " ".join(
        (await blank_handle.get_attribute("aria-label") or "").split()
    )
    item_match = re.fullmatch(
        rf"and ({group_number}\.\d+): Name contains an unset filter value",
        blank_label,
    )
    if item_match is None:
        raise _CandidateError(
            f"The new condition had an unexpected label: {blank_label!r}."
        )

    row = page.locator(f'div[aria-label^="and {item_match.group(1)}:"]')
    field_button = row.locator(
        '[data-testid="autocomplete-button"][role="button"]'
    ).filter(has_text=re.compile(r"^Name$"))
    await (await _require_one(
        page,
        field_button,
        f"new condition field in group {group_number}",
        timeout_ms,
        exact_text="Name",
    )).click()

    field_search = await _require_one(
        page,
        page.get_by_role("combobox", name="Find a field", exact=True),
        "filter field search",
        timeout_ms,
    )
    await field_search.fill(_CHANGE_REQUEST_FIELD)
    await (await _require_one(
        page,
        page.get_by_role("option").filter(
            has_text=re.compile(rf"^{re.escape(_CHANGE_REQUEST_FIELD)}$")
        ),
        f"{_CHANGE_REQUEST_FIELD!r} field option",
        timeout_ms,
        exact_text=_CHANGE_REQUEST_FIELD,
    )).click()

    default_operator = "has any of"
    operator_button = row.locator(
        '[data-testid="autocomplete-button"][role="button"]'
    ).filter(has_text=re.compile(rf"^{re.escape(default_operator)}$"))
    await (await _require_one(
        page,
        operator_button,
        f"new condition operator in group {group_number}",
        timeout_ms,
        exact_text=default_operator,
    )).click()
    option_text = f"{operator}..." if operator == "is exactly" else operator
    await (await _require_one(
        page,
        page.get_by_role("option").filter(
            has_text=re.compile(rf"^{re.escape(option_text)}$")
        ),
        f"{operator!r} operator option",
        timeout_ms,
        exact_text=option_text,
    )).click()

    if value is not None:
        value_button = row.locator(
            '[data-testid="autocomplete-button"][role="button"]'
        ).filter(has_text=re.compile(r"^Select an option$"))
        await (await _require_one(
            page,
            value_button,
            f"new condition value in group {group_number}",
            timeout_ms,
            exact_text="Select an option",
        )).click()
        await (await _require_one(
            page,
            page.get_by_role("option").filter(
                has_text=re.compile(rf"^{re.escape(value)}$")
            ),
            f"{value!r} value option",
            timeout_ms,
            exact_text=value,
        )).click()

    if not await _change_request_condition_exists(
        page, group_number, operator, value
    ):
        expected = f"{_CHANGE_REQUEST_FIELD} {operator}"
        if value:
            expected += f" {value}"
        raise _CandidateError(
            f"The new condition in group {group_number} did not become {expected!r}."
        )


async def _apply_change_request_filters(page: Page, timeout_ms: int) -> None:
    apply_button = await _require_one(
        page,
        page.get_by_role("button", name="Apply", exact=True),
        "Apply filters button",
        timeout_ms,
        exact_text="Apply",
    )
    await apply_button.click()
    warning = page.get_by_role(
        "heading", name=_CHANGE_REQUEST_WARNING, exact=True
    )
    try:
        await warning.wait_for(state="visible", timeout=min(timeout_ms, 4_000))
    except PlaywrightError:
        await page.wait_for_timeout(2_500)
        return

    dialog = warning.locator('xpath=ancestor::*[@role="dialog"][1]')
    continue_button = dialog.get_by_role("button", name="Continue", exact=True)
    if await continue_button.count() == 0:
        continue_button = page.get_by_role(
            "button", name="Continue", exact=True
        )
    await (await _require_one(
        page,
        continue_button,
        "automation warning Continue button",
        timeout_ms,
        exact_text="Continue",
    )).click()
    await page.wait_for_timeout(2_500)


async def change_request_add_filter(
    page: Page, settings: Settings
) -> ActionReport:
    """Add the two QA Review status filters to their existing condition groups."""
    action_name = "change_request_add_filter"
    report = _new_report(action_name, page)
    timeout_ms = settings.browser_timeout_ms
    changed = False

    try:
        await page.locator('header[data-testid="appTopbar"]').wait_for(
            timeout=timeout_ms
        )
        await _open_change_request_filters(page, timeout_ms)

        for group_number, operator, value in _CHANGE_REQUEST_CONDITIONS:
            label = f"{_CHANGE_REQUEST_FIELD} {operator}"
            if value:
                label += f" {value}"
            if await _change_request_condition_exists(
                page, group_number, operator, value
            ):
                report.results.append(CandidateResult(
                    candidate=f"Condition group {group_number}: {label}",
                    outcome=Outcome.SKIPPED,
                    message="The exact condition is already configured.",
                ))
                continue

            await _configure_change_request_condition(
                page, group_number, operator, value, timeout_ms
            )
            changed = True
            report.results.append(CandidateResult(
                candidate=f"Condition group {group_number}: {label}",
                outcome=Outcome.SUCCESS,
                message="Added the condition from the saved click inspection.",
            ))

        if changed:
            await _apply_change_request_filters(page, timeout_ms)
        else:
            await page.keyboard.press("Escape")

        await page.reload(wait_until="domcontentloaded")
        await page.locator('header[data-testid="appTopbar"]').wait_for(
            timeout=timeout_ms
        )
        await _open_change_request_filters(page, timeout_ms)
        for group_number, operator, value in _CHANGE_REQUEST_CONDITIONS:
            if not await _change_request_condition_exists(
                page, group_number, operator, value
            ):
                raise _CandidateError(
                    f"Condition group {group_number} did not retain "
                    f"{_CHANGE_REQUEST_FIELD} {operator}"
                    f"{f' {value}' if value else ''} after reload."
                )
        await page.keyboard.press("Escape")
        report.results.append(CandidateResult(
            candidate="Change Request filter reload persistence",
            outcome=Outcome.SUCCESS,
            message="Verified both conditions in their numbered groups after reload.",
        ))
    except (_CandidateError, PlaywrightError) as exc:
        report.results.append(CandidateResult(
            candidate="Change Request filter workflow",
            outcome=Outcome.FAILED,
            message=str(exc),
            details={"stage_url": page.url},
        ))

    return report.finish(page)
