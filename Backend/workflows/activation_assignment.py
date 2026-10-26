"""Activation assignment interface, checklist rules, and workflow orchestration."""

from __future__ import annotations

import re

from playwright.async_api import Error as PlaywrightError, Locator, Page

from Backend.helpers import ActionReport, _CandidateError, _new_report
from Backend.config import Settings
from Backend.helpers import (
    _ASSIGNMENT_AUTOMATION,
    _RESET_AUTOMATION,
    _RESET_AUTOMATION_TEXT,
    _add_root_condition,
    _canonical,
    _click,
    _click_option,
    _close_visibility,
    _groups_named,
    _one,
    _run_validated_section,
    _text,
    _visible,
    _wait_for_interface_save,
    _wait_until,
    _workflow_failure,
)
from Backend.helpers import (
    _configure_assignment_automation,
    _configure_reset_automation,
    _open_automation,
)


# 2. Semantic controls and state checks.
async def _open_activation_details(page: Page, timeout_ms: int) -> None:
    topbar = page.locator('header[data-testid="appTopbar"]')
    await _one(page, topbar, "Airtable top bar", timeout_ms, enabled=False)
    await _click(
        page,
        topbar.get_by_role("link", name="Interfaces", exact=True),
        "Interfaces link",
        timeout_ms,
    )
    await _click(
        page,
        page.get_by_role("link", name="Flow Core", exact=True),
        "Flow Core interface",
        timeout_ms,
    )
    current_page = page.locator(
        'a[data-testid="PageNavigationLeftNavPageMenuItem"]'
        '[aria-current="page"]'
    )
    planning_page = current_page.filter(
        has_text=re.compile(r"^📝 Planning$")
    )
    await _wait_until(
        page,
        lambda: _visible(planning_page),
        "Flow Core Planning page to finish opening",
        timeout_ms,
    )

    activation_link = page.get_by_role(
        "link", name="🚀 Activation", exact=True
    )
    await _click(
        page,
        activation_link,
        "Activation interface page",
        timeout_ms,
    )
    activation_page = current_page.filter(
        has_text=re.compile(r"^🚀 Activation$")
    )
    await _wait_until(
        page,
        lambda: _visible(activation_page),
        "Activation page to become the active interface page",
        timeout_ms,
    )
    await _click(
        page,
        page.get_by_test_id("page-element:levels"),
        "Activation page list",
        timeout_ms,
    )

    sidebar = page.get_by_test_id("page-creator-sidebar")
    await _click(
        page,
        sidebar.locator("p").filter(has_text=re.compile(r"^User actions$")),
        "User actions heading",
        timeout_ms,
    )
    await _click(
        page,
        sidebar.locator(
            '[role="button"][aria-label="Configure: Record detail pages"]'
        ),
        "Record detail pages configuration",
        timeout_ms,
    )
    detail_pages = page.get_by_test_id("popover:Record detail pages")
    await _click(
        page,
        detail_pages.locator(
            '[role="button"]'
            '[aria-label="Customize Flow Core Activation - Media Plan page"]'
        ),
        "Flow Core Activation - Media Plan detail page",
        timeout_ms,
    )
    details = page.get_by_test_id("page-element-expansion-stack-renderer-dialog")
    await _click(
        page,
        details.get_by_test_id("page-element:recordContainer"),
        "record detail container",
        timeout_ms,
    )


async def _click_group(
    page: Page, group: Locator, description: str, timeout_ms: int
) -> None:
    target = await _one(page, group, description, timeout_ms)
    if await target.get_attribute("data-testid") != "selectedPageElement":
        await target.scroll_into_view_if_needed(timeout=timeout_ms)
        await target.dispatch_event("click")

    async def outer_group_is_selected() -> bool:
        try:
            return (
                await group.count() == 1
                and await group.get_attribute("data-testid")
                == "selectedPageElement"
            )
        except PlaywrightError:
            return False

    await _wait_until(
        page,
        outer_group_is_selected,
        f"{description} outer container selection",
        timeout_ms,
    )


async def _select_change_activator(page: Page, timeout_ms: int) -> Locator:
    assign_group = _groups_named(page, "Assign Activator")
    await _click_group(page, assign_group, "Assign Activator group", timeout_ms)
    change_button = assign_group.locator(
        '[data-testid="call-to-action-container"] '
        '[data-cta-button]:has('
        '[role="button"][aria-label="Change Activator"]'
        ') > [role="button"][aria-label="Select element"]'
    )
    await _click(page, change_button, "Change Activator button", timeout_ms)
    return page.get_by_test_id("page-creator-sidebar")


async def _select_checklist_group(
    page: Page, timeout_ms: int, *, qa_buttons: bool
) -> Locator:
    groups = _groups_named(page, "Activator Check List")
    qa_controls = page.locator(
        '[data-testid="call-to-action-container"] [data-cta-button]'
    )
    if qa_buttons:
        group = groups.filter(has=qa_controls)
        description = "Activator Check List group with QA buttons"
        expected_buttons = "Buttons Send for QA, Resend for QA"
    else:
        group = groups.filter(has_not=qa_controls)
        description = "Activator Check List group without QA buttons"
        expected_buttons = "Buttons None"
    await _click_group(page, group, description, timeout_ms)
    sidebar = page.get_by_test_id("page-creator-sidebar")

    async def selected_group_is_confirmed() -> bool:
        if not await _visible(sidebar):
            return False
        return expected_buttons in _text(await sidebar.inner_text())

    await _wait_until(
        page,
        selected_group_is_confirmed,
        f"{description} Buttons setting",
        timeout_ms,
    )
    return sidebar


async def _click_sidebar_heading(
    page: Page, sidebar: Locator, heading: str, timeout_ms: int
) -> None:
    await _click(
        page,
        sidebar.locator("p").filter(
            has_text=re.compile(rf"^{re.escape(heading)}$")
        ),
        f"{heading} settings heading",
        timeout_ms,
    )


async def _open_visibility(
    page: Page, sidebar: Locator, timeout_ms: int
) -> Locator:
    await _click_sidebar_heading(page, sidebar, "Rules", timeout_ms)
    await _click(
        page,
        sidebar.locator(
            '[role="button"][aria-label="open Visibility popover"]'
        ),
        "Visibility condition count",
        timeout_ms,
    )
    dialog = page.get_by_test_id("popover:Filter")
    return await _one(page, dialog, "Visibility Filter dialog", timeout_ms)


async def _filter_labels(dialog: Locator) -> list[str]:
    values = await dialog.locator("[aria-label]").evaluate_all(
        "elements => elements.map(element => element.getAttribute('aria-label'))"
    )
    return [_canonical(value) for value in values if value]


def _condition_labels(labels: list[str]) -> list[str]:
    fields = (
        "Activator",
        "Timestamp: Activation Assigned On",
        "Campaign Status",
        "User Tag (from Activator)",
    )
    return [
        label
        for label in labels
        if ":" in label and any(field in label for field in fields)
    ]


def _nested_group_labels(labels: list[str]) -> list[str]:
    return [
        label
        for label in labels
        if re.match(
            r"^(?:Where |and |or )?\d+: a nested condition group", label
        )
    ]


def _has_condition(labels: list[str], suffix: str) -> bool:
    expected = _canonical(suffix)
    return any(label.endswith(expected) for label in _condition_labels(labels))


def _flat_state(labels: list[str], conditions: tuple[str, ...]) -> bool:
    rows = _condition_labels(labels)
    return (
        len(rows) == len(conditions)
        and all(_has_condition(labels, condition) for condition in conditions)
    )


def _button_visibility_state(labels: list[str], *, final: bool) -> bool:
    conditions = (
        "Activator is not empty",
        "Timestamp: Activation Assigned On is not empty",
    )
    if final:
        conditions += ("Campaign Status is not In QA",)
    return _flat_state(labels, conditions)


def _qa_checklist_state(labels: list[str], *, final: bool) -> bool:
    conditions = (
        "Timestamp: Activation Assigned On is not empty",
        "Campaign Status is none of Live Paused Ended",
    )
    if final:
        conditions += ("User Tag (from Activator) is exactly Current user",)
    return _flat_state(labels, conditions)


def _plain_checklist_state(labels: list[str], *, final: bool) -> bool:
    if not final:
        rows = _condition_labels(labels)
        return (
            len(rows) == 2
            and _has_condition(
                labels, "Campaign Status is any of Live Paused Ended"
            )
            and any(
                _has_condition(labels, condition)
                for condition in (
                    "Timestamp: Activation Assigned On is empty",
                    "Timestamp: Activation Assigned On is not empty",
                )
            )
        )

    rows = _condition_labels(labels)
    expected = (
        ("1.1:", "Campaign Status is any of Live Paused Ended"),
        ("1.2:", "Timestamp: Activation Assigned On is not empty"),
        ("2.1:", "Campaign Status is any of In QA Assigned for Activation"),
        ("2.2:", "Timestamp: Activation Assigned On is not empty"),
        ("2.3:", "User Tag (from Activator) has none of Current user"),
    )
    groups = _nested_group_labels(labels)
    return (
        len(rows) == len(expected)
        and all(
            any(prefix in label and label.endswith(suffix) for label in rows)
            for prefix, suffix in expected
        )
        and len(groups) == 2
        and any(
            label.startswith("1:") or label.startswith("Where 1:")
            for label in groups
        )
        and any(label.startswith("or 2:") for label in groups)
        and all("all of the following" in label for label in groups)
    )


def _plain_conditions_complete(labels: list[str]) -> bool:
    rows = _condition_labels(labels)
    timestamp = _canonical(
        "Timestamp: Activation Assigned On is not empty"
    )
    return (
        len(rows) == 5
        and sum(label.endswith(timestamp) for label in rows) == 2
        and _has_condition(
            labels, "Campaign Status is any of Live Paused Ended"
        )
        and _has_condition(
            labels,
            "Campaign Status is any of In QA Assigned for Activation",
        )
        and _has_condition(
            labels, "User Tag (from Activator) has none of Current user"
        )
    )


async def _plain_checklist_complete(dialog: Locator) -> bool:
    labels = await _filter_labels(dialog)
    if not _plain_checklist_state(labels, final=True):
        return False
    expected = (
        ("conjunction picker for condition group 1", "and"),
        ("conjunction picker for the top level", "or"),
        ("conjunction picker for condition group 2", "and"),
    )
    for picker_label, connector in expected:
        button = dialog.locator(
            f'[aria-label="{picker_label}"] [role="button"]'
        ).filter(has_text=re.compile(rf"^{connector}$"))
        if not await _visible(button):
            return False
    return True


async def _add_group_condition_at(
    page: Page,
    dialog: Locator,
    group_number: int,
    row_number: int,
    timeout_ms: int,
) -> Locator:
    await _click(
        page,
        dialog.get_by_role(
            "button",
            name=f"add conditions and subgroups to condition group {group_number}",
            exact=True,
        ),
        f"condition group {group_number} add button",
        timeout_ms,
    )
    await _click_option(page, "Add condition", timeout_ms, menu=True)
    blank = await _one(
        page,
        dialog.locator(
            f'[aria-label*="{group_number}.{row_number}:"]'
            '[aria-label*="Name contains"]'
        ),
        f"new condition {group_number}.{row_number}",
        timeout_ms,
    )
    return _numbered_condition_row(dialog, group_number, row_number)


def _numbered_condition_row(
    dialog: Locator, group_number: int, row_number: int
) -> Locator:
    number = f"{group_number}.{row_number}:"
    return dialog.locator(f'[aria-label*="{number}"]')


async def _set_condition_connector(
    page: Page,
    dialog: Locator,
    picker_label: str,
    expected: str,
    timeout_ms: int,
) -> None:
    picker = dialog.locator(f'[aria-label="{picker_label}"]')
    expected_button = picker.locator('[role="button"]').filter(
        has_text=re.compile(rf"^{re.escape(expected)}$")
    )
    if await _visible(expected_button):
        return
    current = "or" if expected == "and" else "and"
    await _click(
        page,
        picker.locator('[role="button"]').filter(
            has_text=re.compile(rf"^{current}$")
        ),
        f"{picker_label} connector",
        timeout_ms,
    )
    await _click_option(page, expected, timeout_ms)
    await _wait_until(
        page,
        lambda: _visible(expected_button),
        f"{picker_label} to become {expected}",
        timeout_ms,
    )


async def _configure_condition(
    page: Page,
    row: Locator,
    field: str,
    default_operator: str,
    operator_option: str,
    timeout_ms: int,
    *,
    values: tuple[str, ...] = (),
    value_prompt: str = "Select an option",
) -> None:
    field_button = row.locator(
        '[data-testid="autocomplete-button"][role="button"]'
    ).filter(has_text=re.compile(r"^Name$"))
    await _click(page, field_button, "new condition field", timeout_ms)
    await _click_option(page, field, timeout_ms)

    operator = row.locator(
        '[data-testid="autocomplete-button"][role="button"]'
    ).filter(has_text=re.compile(rf"^{re.escape(default_operator)}$"))
    await _click(page, operator, f"{field!r} operator", timeout_ms)
    await _click_option(page, operator_option, timeout_ms)

    if not values:
        return
    value_button = row.locator('[data-testid="autocomplete-button"]').filter(
        has_text=re.compile(rf"^{re.escape(value_prompt)}$")
    )
    await _click(page, value_button, f"{field!r} value", timeout_ms)
    for value in values:
        await _click_option(page, value, timeout_ms)


async def _apply_button_visibility(
    page: Page, sidebar: Locator, timeout_ms: int
) -> bool:
    dialog = await _open_visibility(page, sidebar, timeout_ms)
    labels = await _filter_labels(dialog)
    if _button_visibility_state(labels, final=True):
        await _close_visibility(page, dialog, timeout_ms)
        return False
    if not _button_visibility_state(labels, final=False):
        raise _CandidateError(
            "Change Activator visibility was neither the inspected two-condition "
            "state nor the exact final three-condition state."
        )

    row = await _add_root_condition(page, dialog, timeout_ms)
    await _configure_condition(
        page,
        row,
        "Campaign Status",
        "is",
        "is not...",
        timeout_ms,
        values=("In QA",),
    )
    await _click(
        page,
        dialog.locator('[aria-label*="Activator is not empty"]'),
        "existing Activator visibility condition",
        timeout_ms,
    )
    if not _button_visibility_state(await _filter_labels(dialog), final=True):
        raise _CandidateError("Change Activator visibility did not reach final state.")
    await _close_visibility(page, dialog, timeout_ms)
    return True


async def _validate_button_visibility(
    page: Page, sidebar: Locator, timeout_ms: int
) -> bool:
    dialog = await _open_visibility(page, sidebar, timeout_ms)
    correct = _button_visibility_state(await _filter_labels(dialog), final=True)
    await _close_visibility(page, dialog, timeout_ms)
    return correct


async def _ensure_change_button(page: Page, timeout_ms: int) -> bool:
    sidebar = await _select_change_activator(page, timeout_ms)
    changed = False

    await _click_sidebar_heading(page, sidebar, "Action", timeout_ms)
    selected_action = sidebar.locator(
        '[role="button"][aria-haspopup="true"]'
    ).filter(has_text=re.compile(r"^(?:Update record|Run automation)$"))
    action = await _one(page, selected_action, "Change Activator action", timeout_ms)
    action_text = _text(await action.inner_text())
    if action_text == "Update record":
        await action.click(timeout=timeout_ms)
        await _click_option(page, "Run automation", timeout_ms)
        changed = True
    elif action_text != "Run automation":
        raise _CandidateError(f"Unexpected Change Activator action: {action_text!r}.")

    await _click_sidebar_heading(page, sidebar, "Appearance", timeout_ms)
    color = await _one(
        page,
        sidebar.locator('[role="button"][aria-label="open Color popover"]'),
        "Change Activator color",
        timeout_ms,
    )
    color_text = _text(await color.inner_text())
    if color_text == "Gray":
        await color.click(timeout=timeout_ms)
        await _click(
            page,
            page.get_by_role("radio", name="Blue", exact=True),
            "Blue color",
            timeout_ms,
        )
        changed = True
    elif color_text != "Blue":
        raise _CandidateError(f"Unexpected Change Activator color: {color_text!r}.")

    await _click_sidebar_heading(page, sidebar, "Automation", timeout_ms)
    assigned = sidebar.filter(has_text=_RESET_AUTOMATION_TEXT)
    if not await _visible(assigned):
        chooser = sidebar.locator('[role="button"][aria-label="open popover"]')
        chooser = await _one(page, chooser, "Automation chooser", timeout_ms)
        if _text(await chooser.inner_text()) != "None":
            raise _CandidateError("Change Activator has an unexpected automation.")
        await chooser.click(timeout=timeout_ms)
        automation_dialog = page.get_by_test_id("popover:Automations")
        automation = automation_dialog.locator('[role="button"]').filter(
            has_text=_RESET_AUTOMATION_TEXT
        )
        try:
            await _click(
                page,
                automation,
                f"{_RESET_AUTOMATION!r} automation",
                timeout_ms,
            )
        except _CandidateError as exc:
            names = await automation_dialog.locator('[role="button"]').evaluate_all(
                "elements => elements.map(element => ({"
                "text: element.innerText, aria: element.getAttribute('aria-label')"
                "})).filter(item => /activator|reset/i.test((item.text || '') + "
                " ' ' + (item.aria || '')))"
            )
            raise _CandidateError(f"{exc} Rendered related automations: {names!r}.")
        changed = True

    if await _apply_button_visibility(page, sidebar, timeout_ms):
        changed = True
    return changed


async def _validate_change_button(page: Page, timeout_ms: int) -> bool:
    sidebar = await _select_change_activator(page, timeout_ms)
    action = sidebar.locator(
        '[role="button"][aria-haspopup="true"]'
    ).filter(has_text=re.compile(r"^Run automation$"))
    color = sidebar.locator('[role="button"][aria-label="open Color popover"]')
    automation = sidebar.filter(has_text=_RESET_AUTOMATION_TEXT)
    action_visible = await _visible(action)
    color_visible = await _visible(color)
    automation_visible = await _visible(automation)
    color_text = _text(await color.inner_text()) if color_visible else "missing"
    if not action_visible or not color_visible or not automation_visible:
        raise _CandidateError(
            "Change Activator validation mismatch: "
            f"action={action_visible}, color={color_text!r}, "
            f"automation={automation_visible}."
        )
    if color_text != "Blue":
        raise _CandidateError(
            f"Change Activator color was {color_text!r}, not 'Blue'."
        )
    if not await _validate_button_visibility(page, sidebar, timeout_ms):
        raise _CandidateError("Change Activator visibility conditions did not match.")
    return True


async def _ensure_plain_checklist(page: Page, timeout_ms: int) -> bool:
    sidebar = await _select_checklist_group(page, timeout_ms, qa_buttons=False)
    dialog = await _open_visibility(page, sidebar, timeout_ms)
    labels = await _filter_labels(dialog)
    if await _plain_checklist_complete(dialog):
        await _close_visibility(page, dialog, timeout_ms)
        return False
    if _plain_conditions_complete(labels):
        await _set_condition_connector(
            page,
            dialog,
            "conjunction picker for condition group 1",
            "and",
            timeout_ms,
        )
        await _set_condition_connector(
            page,
            dialog,
            "conjunction picker for the top level",
            "or",
            timeout_ms,
        )
        await _set_condition_connector(
            page,
            dialog,
            "conjunction picker for condition group 2",
            "and",
            timeout_ms,
        )
        labels = await _filter_labels(dialog)
        if not await _plain_checklist_complete(dialog):
            raise _CandidateError(
                "The complete first-checklist conditions had unexpected group labels: "
                f"{_nested_group_labels(labels)!r}."
            )
        await _close_visibility(page, dialog, timeout_ms)
        return True
    initial_state = _plain_checklist_state(labels, final=False)
    empty_state = not _condition_labels(labels)
    blank_tree = empty_state and any(
        "Name contains an unset filter value" in label for label in labels
    )
    partial_group = (
        any(
            "1.1: Campaign Status is an unset filter value" in label
            for label in labels
        )
        and any(
            "1.2: Name contains an unset filter value" in label
            for label in labels
        )
        and len(_nested_group_labels(labels)) == 1
    )
    if not initial_state and not empty_state and not partial_group:
        raise _CandidateError(
            "The checklist without QA buttons has an unexpected visibility tree: "
            f"{_condition_labels(labels)!r}."
        )

    removals = 2 if initial_state else 1 if partial_group else 0
    for _ in range(removals):
        await _click(
            page,
            dialog.get_by_role("button", name="Remove item 1", exact=True),
            "first checklist condition 1 remove button",
            timeout_ms,
        )
    if partial_group and not await dialog.is_visible():
        dialog = await _open_visibility(page, sidebar, timeout_ms)
    if blank_tree:
        remove_group = dialog.get_by_role(
            "button", name="Remove item 1", exact=True
        )
        for _ in range(2):
            if not await _visible(remove_group):
                break
            await _click(
                page,
                remove_group,
                "incomplete blank condition group remove button",
                timeout_ms,
            )
        if not await dialog.is_visible():
            dialog = await _open_visibility(page, sidebar, timeout_ms)

    empty_group = dialog.get_by_text(
        "Drag conditions here to add them to this group", exact=True
    )
    if not await _visible(empty_group):
        await _click(
            page,
            dialog.get_by_role("button", name="Add condition group", exact=True),
            "first Add condition group button",
            timeout_ms,
        )
    await _click(
        page,
        empty_group,
        "empty first condition group",
        timeout_ms,
    )
    group_1_rows = (
        await _add_group_condition_at(page, dialog, 1, 1, timeout_ms),
        await _add_group_condition_at(page, dialog, 1, 2, timeout_ms),
    )
    await _set_condition_connector(
        page,
        dialog,
        "conjunction picker for condition group 1",
        "and",
        timeout_ms,
    )
    await _configure_condition(
        page,
        group_1_rows[0],
        "Campaign Status",
        "is",
        "is any of...",
        timeout_ms,
        values=("Live", "Paused", "Ended"),
    )
    await _configure_condition(
        page,
        group_1_rows[1],
        "Timestamp: Activation Assigned On",
        "is",
        "is not empty",
        timeout_ms,
    )
    await dialog.click(timeout=timeout_ms)

    await _click(
        page,
        dialog.get_by_role("button", name="Add condition group", exact=True),
        "second Add condition group button",
        timeout_ms,
    )
    await _set_condition_connector(
        page,
        dialog,
        "conjunction picker for the top level",
        "or",
        timeout_ms,
    )
    await _click(
        page,
        dialog.get_by_text(
            "Drag conditions here to add them to this group", exact=True
        ),
        "empty second condition group",
        timeout_ms,
    )
    group_2_rows = (
        await _add_group_condition_at(page, dialog, 2, 1, timeout_ms),
        await _add_group_condition_at(page, dialog, 2, 2, timeout_ms),
        await _add_group_condition_at(page, dialog, 2, 3, timeout_ms),
    )
    await _set_condition_connector(
        page,
        dialog,
        "conjunction picker for condition group 2",
        "and",
        timeout_ms,
    )
    await _configure_condition(
        page,
        group_2_rows[0],
        "Campaign Status",
        "is",
        "is any of...",
        timeout_ms,
        values=("In QA", "Assigned for Activation"),
    )
    await _configure_condition(
        page,
        group_2_rows[1],
        "Timestamp: Activation Assigned On",
        "is",
        "is not empty",
        timeout_ms,
    )
    await _configure_condition(
        page,
        group_2_rows[2],
        "User Tag (from Activator)",
        "has any of",
        "has none of...",
        timeout_ms,
        values=("Current user",),
        value_prompt="Add a user",
    )
    await dialog.click(timeout=timeout_ms)
    if not await _plain_checklist_complete(dialog):
        raise _CandidateError(
            "The checklist without QA buttons did not reach its final tree."
        )
    await _close_visibility(page, dialog, timeout_ms)
    return True


async def _validate_plain_checklist(page: Page, timeout_ms: int) -> bool:
    sidebar = await _select_checklist_group(page, timeout_ms, qa_buttons=False)
    dialog = await _open_visibility(page, sidebar, timeout_ms)
    correct = await _plain_checklist_complete(dialog)
    await _close_visibility(page, dialog, timeout_ms)
    return correct


async def _ensure_qa_checklist(page: Page, timeout_ms: int) -> bool:
    sidebar = await _select_checklist_group(page, timeout_ms, qa_buttons=True)
    dialog = await _open_visibility(page, sidebar, timeout_ms)
    labels = await _filter_labels(dialog)
    if _qa_checklist_state(labels, final=True):
        await _close_visibility(page, dialog, timeout_ms)
        return False
    if not _qa_checklist_state(labels, final=False):
        raise _CandidateError(
            "The checklist with QA buttons has an unexpected visibility tree."
        )

    row = await _add_root_condition(page, dialog, timeout_ms)
    await _configure_condition(
        page,
        row,
        "User Tag (from Activator)",
        "has any of",
        "is exactly...",
        timeout_ms,
        values=("Current user",),
        value_prompt="Add a user",
    )
    await _click(
        page,
        dialog.locator(
            '[aria-label*="User Tag (from Activator) is exactly Current user"]'
        ),
        "new Current user condition",
        timeout_ms,
    )
    if not _qa_checklist_state(await _filter_labels(dialog), final=True):
        raise _CandidateError(
            "The checklist with QA buttons did not reach its final state."
        )
    await _close_visibility(page, dialog, timeout_ms)
    return True


async def _validate_qa_checklist(page: Page, timeout_ms: int) -> bool:
    sidebar = await _select_checklist_group(page, timeout_ms, qa_buttons=True)
    dialog = await _open_visibility(page, sidebar, timeout_ms)
    correct = _qa_checklist_state(await _filter_labels(dialog), final=True)
    await _close_visibility(page, dialog, timeout_ms)
    return correct


async def _configure_interface(
    page: Page, report: ActionReport, timeout_ms: int
) -> bool:
    items = (
        "Change Activator button",
        "Activator Check List without QA buttons",
        "Activator Check List with QA buttons",
    )

    async def apply(item: str) -> bool:
        if item == items[0]:
            return await _ensure_change_button(page, timeout_ms)
        if item == items[1]:
            return await _ensure_plain_checklist(page, timeout_ms)
        return await _ensure_qa_checklist(page, timeout_ms)

    async def validate(item: str) -> bool:
        if item == items[0]:
            return await _validate_change_button(page, timeout_ms)
        if item == items[1]:
            return await _validate_plain_checklist(page, timeout_ms)
        return await _validate_qa_checklist(page, timeout_ms)

    return await _run_validated_section(
        page,
        report,
        "Flow Core Activation interface",
        items,
        apply,
        validate,
        timeout_ms,
        save_waiter=_wait_for_interface_save,
    )

# 3. Workflow entry point.
async def configure_activation_assignment(page: Page, settings: Settings) -> ActionReport:
    """Configure the inspected Activation interface and its two automations."""
    action_name = 'configure_activation_assignment'
    report = _new_report(action_name, page)
    timeout_ms = settings.browser_timeout_ms
    try:
        if "/automations" not in page.url:
            await _open_activation_details(page, timeout_ms)
            await _configure_interface(page, report, timeout_ms)
            return report.finish(page)
        assignment_canvas = await _open_automation(
            page, _ASSIGNMENT_AUTOMATION, timeout_ms
        )
        if not await _configure_assignment_automation(
            page, report, assignment_canvas, timeout_ms
        ):
            return report.finish(page)

        reset_canvas = await _open_automation(page, _RESET_AUTOMATION, timeout_ms)
        await _configure_reset_automation(page, report, reset_canvas, timeout_ms)
    except (_CandidateError, PlaywrightError) as exc:
        _workflow_failure(page, report, 'Activation assignment workflow', exc)
    return report.finish(page)

