"""Workflow catalogue, common results, and shared Airtable controls."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import StrEnum
from importlib import import_module
import re
import time
from typing import Any

from playwright.async_api import ElementHandle, Error as PlaywrightError, Locator, Page
from Backend.config import Settings, lebanon_now


# 1. Common result types and semantic controls.
class Outcome(StrEnum):
    SUCCESS = "success"
    WARNING = "warning"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(slots=True)
class CandidateResult:
    candidate: str
    outcome: Outcome
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ActionReport:
    action: str
    target_url: str
    started_at: str
    results: list[CandidateResult] = field(default_factory=list)
    final_url: str | None = None
    finished_at: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(
            item.outcome is not Outcome.FAILED for item in self.results
        )

    @property
    def has_warnings(self) -> bool:
        return any(item.outcome == Outcome.WARNING for item in self.results)

    @property
    def status(self) -> str:
        if not self.ok:
            return "Failed"
        if self.has_warnings:
            return "Success with warnings"
        return "Success" if any(item.outcome == Outcome.SUCCESS for item in self.results) else "Skipped"

    def finish(self, page: Page | None = None) -> "ActionReport":
        if page is not None:
            self.final_url = page.url
        self.finished_at = lebanon_now().isoformat()
        return self

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data


class _CandidateError(RuntimeError):
    pass


def _new_report(action: str, page: Page) -> ActionReport:
    return ActionReport(action=action, target_url=page.url, started_at=lebanon_now().isoformat())


def failed_action_report(action: str, url: str, message: str) -> ActionReport:
    """Create a report for a URL-level failure before an action can complete."""
    report = ActionReport(action=action, target_url=url, started_at=lebanon_now().isoformat())
    report.results.append(
        CandidateResult(candidate="URL", outcome=Outcome.FAILED, message=message)
    )
    return report.finish()


async def _require_one(
    page: Page,
    locator: Locator,
    description: str,
    timeout_ms: int,
    *,
    exact_text: str | None = None,
) -> ElementHandle:
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        candidates: list[ElementHandle] = []
        for handle in await locator.element_handles():
            try:
                normalized_text = " ".join((await handle.inner_text()).split())
                text_matches = exact_text is None or normalized_text == exact_text
                if (
                    await handle.is_visible()
                    and await handle.is_enabled()
                    and text_matches
                ):
                    candidates.append(handle)
            except PlaywrightError:
                continue

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise _CandidateError(
                f"Found {len(candidates)} visible, enabled candidates for {description}; "
                "refusing to choose by position."
            )
        if time.monotonic() >= deadline:
            raise _CandidateError(f"Could not find a usable {description}.")
        await page.wait_for_timeout(250)


# 2. One catalogue for every workflow. Append new entries with their addition date.
# Insertion order records addition order within the same day; unknown dates sort last.
Action = Callable[[Page, Settings], Awaitable[ActionReport]]


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    module: str
    writes_data: bool
    added_on: date | None = None


_ACTIONS: dict[str, ActionDefinition] = {
    "smart_import_core": ActionDefinition("Backend.workflows.smart_import_core", True),
    "remove_publicis_media_team_signature": ActionDefinition("Backend.workflows.remove_publicis_media_team_signature", True),
    "hide_suggested_metric": ActionDefinition("Backend.workflows.hide_suggested_metric", True),
    "hide_delete_button": ActionDefinition("Backend.workflows.hide_delete_button", True),
    "change_request_add_filter": ActionDefinition("Backend.workflows.change_request_add_filter", True, date(2026, 10, 2)),
    "configure_activation_assignment": ActionDefinition("Backend.workflows.activation_assignment", True, date(2026, 10, 7)),
    "configure_activation_automation_scripts": ActionDefinition("Backend.workflows.activation_scripts", True, date(2026, 10, 8)),
    "hide_suggestion_details": ActionDefinition("Backend.workflows.suggestion_details", True, date(2026, 10, 12)),
    "configure_activation_qa_visibility": ActionDefinition("Backend.workflows.activation_qa_visibility", True, date(2026, 10, 12)),
    "push_master_apps": ActionDefinition("Backend.workflows.push_master_apps", True, date(2026, 10, 13)),
    "Assign_Change_Activator": ActionDefinition("Backend.workflows.assign_change_activator", True, date(2026, 10, 15)),
    "unsync_adsets_metrics": ActionDefinition("Backend.workflows.adsets_metrics_sync", True, date(2026, 10, 23)),
}
_PINNED_ACTIONS = ("change_request_add_filter", "push_master_apps")


def _action_definition(name: str) -> ActionDefinition:
    try:
        return _ACTIONS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown action {name!r}. Available actions: {', '.join(list_actions())}") from exc


def list_actions() -> tuple[str, ...]:
    """List all workflows available through the normal CLI run command."""
    return tuple(sorted(_ACTIONS))


def action_added_on(name: str) -> date | None:
    """Return the recorded addition date; never infer unknown dates."""
    return _action_definition(name).added_on


def launcher_actions() -> tuple[str, ...]:
    """Four newest non-pinned workflows, followed by the two fixed workflows."""
    ordered = sorted(enumerate(_ACTIONS), key=lambda item: (_ACTIONS[item[1]].added_on or date.min, item[0]), reverse=True)
    recent = tuple(name for _, name in ordered if name not in _PINNED_ACTIONS)[:4]
    return recent + _PINNED_ACTIONS


def action_writes_data(name: str) -> bool:
    return _action_definition(name).writes_data


async def run_action(name: str, page: Page, settings: Settings) -> ActionReport:
    """Load only the selected task, after shared definitions are initialized."""
    definition = _action_definition(name)
    action: Action = getattr(import_module(definition.module), name)
    return await action(page, settings)


# 3. Shared navigation and validation controls.

_ASSIGNMENT_AUTOMATION = (
    "[Media Plan] Button | Activator Assigned to Campaign Notification"
)


_RESET_AUTOMATION = "Change Activator – Reset Campaign Status"


_RESET_AUTOMATION_TEXT = re.compile(
    r"Change Activator.*Reset Campaign Status"
)


_SECTION_RETRIES = 1


def _text(value: str) -> str:
    return " ".join(value.split())


def _canonical(value: str) -> str:
    return _text(value.replace(",", "").replace("…", "..."))


def _workflow_failure(page: Page, report: ActionReport, candidate: str, error: Exception) -> None:
    report.results.append(CandidateResult(candidate, Outcome.FAILED, str(error), {"stage_url": page.url}))


async def _one(
    page: Page,
    locator: Locator,
    description: str,
    timeout_ms: int,
    *,
    enabled: bool = True,
) -> Locator:
    """Return a live locator only when its semantic query is unambiguous."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        try:
            count = await locator.count()
            if count > 1:
                raise _CandidateError(
                    f"Found {count} candidates for {description}; refusing to "
                    "choose by position."
                )
            if count == 1 and await locator.is_visible():
                if not enabled or await locator.is_enabled():
                    return locator
        except PlaywrightError:
            pass
        if time.monotonic() >= deadline:
            raise _CandidateError(f"Could not find a usable {description}.")
        await page.wait_for_timeout(250)


async def _click(
    page: Page,
    locator: Locator,
    description: str,
    timeout_ms: int,
) -> None:
    target = await _one(page, locator, description, timeout_ms)
    await target.scroll_into_view_if_needed(timeout=timeout_ms)
    await target.click(timeout=timeout_ms)


async def _visible(locator: Locator) -> bool:
    try:
        return await locator.count() == 1 and await locator.is_visible()
    except PlaywrightError:
        return False


async def _wait_until(
    page: Page,
    predicate: Callable[[], Awaitable[bool]],
    description: str,
    timeout_ms: int,
) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        if await predicate():
            return
        if time.monotonic() >= deadline:
            raise _CandidateError(f"Timed out waiting for {description}.")
        await page.wait_for_timeout(250)


async def _wait_for_interface_save(page: Page, timeout_ms: int) -> None:
    header = page.get_by_test_id("page-creator-chrome-header")
    saved_statuses = (
        header.get_by_text("All changes saved", exact=True),
        header.get_by_text("No changes", exact=True),
        header.get_by_text("Interface has unpublished changes", exact=True),
    )

    async def saved() -> bool:
        return any([await _visible(status) for status in saved_statuses])

    await _wait_until(page, saved, "Interface Designer save state", timeout_ms)


async def _run_validated_section(
    page: Page,
    report: ActionReport,
    section: str,
    items: tuple[str, ...],
    apply_item: Callable[[str], Awaitable[bool]],
    validate_item: Callable[[str], Awaitable[bool]],
    timeout_ms: int,
    *,
    save_waiter: Callable[[Page, int], Awaitable[None]] | None = None,
    retries: int = _SECTION_RETRIES,
) -> bool:
    """Apply a section, validate every item, and retry only unresolved items."""
    pending = list(items)
    changed: set[str] = set()
    attempts = dict.fromkeys(items, 0)
    errors: dict[str, str] = {}

    for _ in range(retries + 1):
        apply_failed = False
        for item in pending:
            attempts[item] += 1
            try:
                if await apply_item(item):
                    changed.add(item)
            except (_CandidateError, PlaywrightError) as exc:
                apply_failed = True
                errors.setdefault(item, str(exc))

        save_error: str | None = None
        if save_waiter is not None and not apply_failed:
            try:
                await save_waiter(page, timeout_ms)
            except (_CandidateError, PlaywrightError) as exc:
                save_error = str(exc)

        pending = []
        for item in items:
            try:
                correct = await validate_item(item)
            except (_CandidateError, PlaywrightError) as exc:
                correct = False
                errors.setdefault(item, str(exc))
            if not correct or save_error:
                pending.append(item)
                errors[item] = errors.get(item) or save_error or (
                    "Expected final state was not present."
                )
            else:
                errors.pop(item, None)
        if not pending:
            break

    for item in items:
        failed = item in pending
        report.results.append(
            CandidateResult(
                candidate=f"{section}: {item}",
                outcome=(
                    Outcome.FAILED
                    if failed
                    else Outcome.SUCCESS
                    if item in changed
                    else Outcome.SKIPPED
                ),
                message=(
                    f"Could not apply {item!r}: {errors[item]}"
                    if failed
                    else f"Applied and validated {item!r}."
                    if item in changed
                    else f"{item!r} is already correct; section validated."
                ),
                details={"attempts": attempts[item], "section": section},
            )
        )
    report.results.append(
        CandidateResult(
            candidate=f"{section} section validation",
            outcome=Outcome.FAILED if pending else Outcome.SUCCESS,
            message=(
                f"Section failed; unresolved items: {', '.join(pending)}."
                if pending
                else "Entire expected section state validated."
            ),
            details={"section": section, "unresolved_items": pending.copy()},
        )
    )
    return not pending


async def _validation_only() -> bool:
    return False


async def _open_activation_qa_details(page: Page, timeout_ms: int) -> None:
    topbar = page.locator('header[data-testid="appTopbar"]')
    await _one(page, topbar, "Airtable top bar", timeout_ms, enabled=False)
    await _click(
        page,
        topbar.get_by_role("link", name="Interfaces", exact=True),
        "Interfaces link",
        timeout_ms,
    )
    navigation = page.get_by_test_id("PageNavigationLeftNav")
    flow_core = navigation.get_by_role("link", name="Flow Core", exact=True)
    await _click(page, flow_core, "Flow Core interface", timeout_ms)

    # 6. Expanding Flow Core can put a newly rendered page under the mouse and
    # leave its tooltip covering Activation. Move to a stable top-bar target.
    await topbar.get_by_role(
        "link", name="Interfaces", exact=True
    ).hover(timeout=timeout_ms)

    async def sidebar_tooltips_closed() -> bool:
        return await page.locator('[role="tooltip"]:visible').count() == 0

    await _wait_until(
        page,
        sidebar_tooltips_closed,
        "Flow Core sidebar tooltips to close",
        timeout_ms,
    )

    bundle = page.locator(
        '[data-testid="PageNavigationLeftNavPageBundleMenuItem"]'
        '[data-tutorial-selector-id='
        '"pageNavigationLeftNavPageBundleMenuItemFlowCore"]'
    )
    activation = bundle.locator(
        'a[data-testid="PageNavigationLeftNavPageMenuItem"]'
    ).filter(has_text=re.compile(r"Activation$"))
    await _click(page, activation, "Activation interface page", timeout_ms)
    current_activation = page.locator(
        'a[data-testid="PageNavigationLeftNavPageMenuItem"]'
        '[aria-current="page"]'
    ).filter(has_text=re.compile(r"Activation$"))
    await _wait_until(
        page,
        lambda: _visible(current_activation),
        "Activation page to become active",
        timeout_ms,
    )

    await _click(
        page,
        page.get_by_test_id("page-element:levels"),
        "Activation page list",
        timeout_ms,
    )
    await _click(
        page,
        page.get_by_role(
            "button", name="Configure: Record detail pages", exact=True
        ),
        "Click into record details configuration",
        timeout_ms,
    )
    detail_pages = page.get_by_test_id("popover:Record detail pages")
    await _click(
        page,
        detail_pages.get_by_role(
            "button",
            name="Customize Flow Core Activation - Media Plan page",
            exact=True,
        ),
        "Flow Core Activation - Media Plan page",
        timeout_ms,
    )
    await _one(
        page,
        page.get_by_test_id("page-element-expansion-stack-renderer-dialog"),
        "Activation Details dialog",
        timeout_ms,
        enabled=False,
    )


def _record_container(page: Page) -> Locator:
    return page.get_by_test_id(
        "page-element-expansion-stack-renderer-dialog"
    ).get_by_test_id("page-element:recordContainer")


def _groups_named(page: Page, title: str) -> Locator:
    exact_title = _record_container(page).get_by_test_id(
        "editableSectionTitle"
    ).filter(
        has_text=re.compile(rf"^{re.escape(title)}$")
    )
    sections = exact_title.locator(
        'xpath=ancestor::*[@data-testid="section-element"][1]'
    )
    return sections.locator(
        ':scope > div > [role="button"][aria-label="Select element"]'
    )


async def _close_visibility(
    page: Page, dialog: Locator, timeout_ms: int
) -> None:
    await _click(
        page,
        dialog.get_by_role("button", name="Close", exact=True),
        "Visibility Filter close button",
        timeout_ms,
    )


async def _click_option(
    page: Page, name: str, timeout_ms: int, *, menu: bool = False
) -> None:
    locator = (
        page.get_by_role("menuitem", name=name, exact=True)
        if menu
        else page.get_by_role("option", name=name, exact=True)
    )
    await _click(page, locator, f"{name!r} option", timeout_ms)


async def _add_root_condition(
    page: Page, dialog: Locator, timeout_ms: int
) -> Locator:
    await _click(
        page,
        dialog.get_by_role("button", name="Add condition", exact=True),
        "Add condition button",
        timeout_ms,
    )
    blank = dialog.locator('[aria-label*="Name contains"]')
    blank = await _one(page, blank, "new blank visibility condition", timeout_ms)
    return await _stable_condition_row(dialog, blank)


async def _stable_condition_row(dialog: Locator, blank: Locator) -> Locator:
    label = _canonical(await blank.get_attribute("aria-label") or "")
    match = re.match(r"^((?:Where |and |or )?\d+(?:\.\d+)?):", label)
    if match is None:
        raise _CandidateError(
            f"New visibility condition had an unexpected label: {label!r}."
        )
    return dialog.locator(f'[aria-label^="{match.group(1)}:"]')


# 4. Core save/validation policies differ from the controls above; preserve both.
_SMART_IMPORT_SECTION_RETRIES = 2


async def _wait_for_core_interface_save(page: Page, timeout_ms: int) -> None:
    """Wait until Interface Designer reports that the table change is saved."""
    await page.wait_for_timeout(500)
    indicator = page.get_by_test_id("globalStatusIndicator")
    visible_indicators = [
        handle for handle in await indicator.element_handles()
        if await handle.is_visible()
    ]
    if len(visible_indicators) > 1:
        raise _CandidateError(
            "Found multiple visible Interface Designer status indicators."
        )
    if len(visible_indicators) == 1:
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            normalized = " ".join((await indicator.inner_text()).split())
            if (
                normalized == "All changes saved"
                or normalized.startswith("No changes")
                or normalized.startswith("Interface has unpublished changes")
            ):
                return
            if time.monotonic() >= deadline:
                break
            await page.wait_for_timeout(250)
    status = page.get_by_text("All changes saved", exact=True)
    if not any([
        await handle.is_visible() for handle in await status.element_handles()
    ]):
        status = page.get_by_text(re.compile(
            r"^No changes(?:\s*[·•-]\s*Last published.*)?$"
        ))
    await _require_one(
        page,
        status,
        "Interface Designer saved status ('All changes saved' or 'No changes')",
        timeout_ms,
    )


async def _run_core_validated_section(
    page: Page,
    report: ActionReport,
    section: str,
    items: tuple[str, ...],
    apply_item: Callable[[str], Awaitable[bool]],
    validate_item: Callable[[str], Awaitable[bool]],
    timeout_ms: int,
    *,
    wait_for_save: bool = False,
) -> bool:
    """Apply a full section, then validate all targets and repair only failures."""
    pending = list(items)
    changed: set[str] = set()
    attempts = dict.fromkeys(items, 0)
    errors: dict[str, str] = {}
    for _ in range(_SMART_IMPORT_SECTION_RETRIES + 1):
        for item in pending:
            attempts[item] += 1
            try:
                if await apply_item(item):
                    changed.add(item)
            except (_CandidateError, PlaywrightError) as exc:
                errors[item] = str(exc)

        save_error = None
        if wait_for_save:
            try:
                await _wait_for_core_interface_save(page, timeout_ms)
            except (_CandidateError, PlaywrightError) as exc:
                save_error = str(exc)

        # Poll whole-section snapshots for asynchronous state updates. No writes
        # occur during validation, including when an earlier item regresses.
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            pending = []
            for item in items:
                try:
                    correct = await validate_item(item)
                    if correct and save_error is None:
                        errors.pop(item, None)
                    else:
                        pending.append(item)
                        errors[item] = save_error or "Expected final state did not persist."
                except (_CandidateError, PlaywrightError) as exc:
                    pending.append(item)
                    errors[item] = str(exc)
            if not pending or time.monotonic() >= deadline or save_error:
                break
            await page.wait_for_timeout(250)
        if not pending:
            break

    for item in items:
        failed = item in pending
        report.results.append(
            CandidateResult(
                candidate=f"{section}: {item}",
                outcome=(Outcome.FAILED if failed else
                         Outcome.SUCCESS if item in changed else Outcome.SKIPPED),
                message=(
                    f"Could not apply {item!r}: {errors[item]}"
                    if failed else
                    f"Applied and validated {item!r}." if item in changed else
                    f"{item!r} is already correct; section validated."
                ),
                details={"attempts": attempts[item], "section": section},
            )
        )
    report.results.append(
        CandidateResult(
            candidate=f"{section} section validation",
            outcome=Outcome.FAILED if pending else Outcome.SUCCESS,
            message=(
                f"Section FAILED after {_SMART_IMPORT_SECTION_RETRIES + 1} attempts. "
                f"Unresolved items: {', '.join(pending)}."
                if pending else "Entire expected section state validated."
            ),
            details={"section": section, "unresolved_items": pending.copy()},
        )
    )
    return not pending


# 5. Activation automation controls reused by assignment and script workflows.
_SCRIPT_INPUT = "recordId"


_RUN_SCRIPT_SUMMARY = "Run a script Custom script from code editor"


_OLD_ASSIGNMENT_ACTION = (
    "Update record Campaign Status and Timestamp: Activation Assigned On"
)


_ASSIGNMENT_SCRIPT = r'''const inputConfig = input.config();
const recordId = inputConfig.recordId?.trim();

if (!recordId) {
    throw new Error("Missing recordId input.");
}

const table = base.getTable("Media Plan");

// Get the record
const record = await table.selectRecordAsync(recordId);

if (!record) {
    throw new Error(`Media Plan record not found: ${recordId}`);
}

// Get current Campaign Status
const campaignStatus = record.getCellValue("Campaign Status");

console.log("Record ID:", recordId);
console.log("Current Campaign Status:", campaignStatus?.name || "Empty");

// Timestamp is ALWAYS updated
const fieldsToUpdate = {
    "Timestamp: Activation Assigned On": new Date().toISOString()
};

// Only change Campaign Status if currently Briefed
if (campaignStatus?.name === "Briefed") {
    fieldsToUpdate["Campaign Status"] = {
        name: "Assigned for Activation"
    };

    console.log(
        "Campaign Status will change: Briefed → Assigned for Activation"
    );
} else {
    console.log(
        `Campaign Status will remain unchanged: ${campaignStatus?.name || "Empty"}`
    );
}

// Actually update the Airtable record
await table.updateRecordAsync(recordId, fieldsToUpdate);

console.log("✅ Record successfully updated.");
console.log("✅ Timestamp: Activation Assigned On updated.");

if (campaignStatus?.name === "Briefed") {
    console.log("✅ Campaign Status updated to Assigned for Activation.");
}
'''


_RESET_SCRIPT = r'''const inputConfig = input.config();
const recordId = inputConfig.recordId?.trim();

if (!recordId) {
    throw new Error("Missing recordId input.");
}

const table = base.getTable("Media Plan");

// Get current record
const record = await table.selectRecordAsync(recordId);

if (!record) {
    throw new Error(`Media Plan record not found: ${recordId}`);
}

// Get current Campaign Status
const campaignStatus = record.getCellValue("Campaign Status");

console.log(
    "Current Campaign Status:",
    campaignStatus?.name || "Empty"
);

// These fields are ALWAYS cleared
const fieldsToUpdate = {
    "Activator": [],
    "Timestamp: Activation Assigned On": null
};

// Only reset status if currently Assigned for Activation
if (campaignStatus?.name === "Assigned for Activation") {
    fieldsToUpdate["Campaign Status"] = {
        name: "Briefed"
    };

    console.log(
        "Campaign Status will change: Assigned for Activation → Briefed"
    );
} else {
    console.log(
        `Campaign Status will remain unchanged: ${campaignStatus?.name || "Empty"}`
    );
}

// Apply all changes
await table.updateRecordAsync(recordId, fieldsToUpdate);

console.log("✅ Activator cleared.");
console.log("✅ Activation Assigned On timestamp cleared.");

if (campaignStatus?.name === "Assigned for Activation") {
    console.log("✅ Campaign Status reset to Briefed.");
}

console.log("✅ Change Activator completed successfully.");
'''


async def _open_automation(
    page: Page, automation_name: str, timeout_ms: int
) -> Locator:
    item = page.locator(
        f'[role="button"][aria-label="{automation_name}"]'
    )
    await _click(page, item, f"{automation_name!r} automation", timeout_ms)
    canvas = page.get_by_test_id("workflows-canvas")
    return await _one(page, canvas, "automation workflow canvas", timeout_ms)


def _workflow_action(canvas: Locator, summary: str) -> Locator:
    if summary == _OLD_ASSIGNMENT_ACTION:
        return canvas.get_by_text(
            "Campaign Status and Timestamp: Activation Assigned On",
            exact=True,
        ).locator('xpath=ancestor::*[@role="button"][1]')
    return canvas.get_by_role("button").filter(
        has_text=re.compile(rf"^{re.escape(summary)}$")
    )


def _run_script_summaries(canvas: Locator) -> Locator:
    return canvas.get_by_text(
        "Custom script from code editor", exact=True
    )


def _assignment_outer_group(canvas: Locator) -> Locator:
    return canvas.get_by_text(
        "If Share Brief with Pending Assets is empty", exact=True
    ).locator('xpath=ancestor::*[@role="group"][1]')


async def _delete_assignment_update(
    page: Page, canvas: Locator, timeout_ms: int
) -> bool:
    old_action = _workflow_action(canvas, _OLD_ASSIGNMENT_ACTION)
    count = await old_action.count()
    if count > 1:
        raise _CandidateError(
            f"Found {count} {_OLD_ASSIGNMENT_ACTION!r} actions; refusing deletion."
        )
    if count == 0:
        return False

    await canvas.click(timeout=timeout_ms)
    await _click(page, old_action, _OLD_ASSIGNMENT_ACTION, timeout_ms)
    focused = page.get_by_test_id("focused-workflow-node")
    await _click(
        page,
        focused.locator(
            ':scope > [role="button"][tabindex="-1"] '
            '[role="button"][aria-label="Open action options menu"]'
        ),
        "assignment update action options",
        timeout_ms,
    )
    await _click_option(page, "Delete action", timeout_ms, menu=True)
    await _click(
        page,
        page.get_by_role("button", name="Delete", exact=True),
        "Delete action confirmation",
        timeout_ms,
    )

    async def deleted() -> bool:
        return await old_action.count() == 0

    await _wait_until(page, deleted, "assignment update action deletion", timeout_ms)
    return True


async def _add_assignment_script(
    page: Page, canvas: Locator, timeout_ms: int
) -> None:
    group = _assignment_outer_group(canvas)
    await _click(
        page,
        group,
        "assignment conditional group after deletion",
        timeout_ms,
    )
    add_action = group.locator(
        ':scope > div > [role="button"][tabindex="-1"] '
        '> [role="button"][aria-haspopup="true"]:not([aria-label])'
    )
    await _click(
        page,
        add_action,
        "add action control attached to assignment conditional group",
        timeout_ms,
    )
    await _click_option(page, "Run script", timeout_ms, menu=True)


async def _add_reset_script(
    page: Page, canvas: Locator, timeout_ms: int
) -> None:
    await _click(
        page,
        canvas.get_by_role(
            "button", name="Add advanced logic or action", exact=True
        ),
        "Add advanced logic or action",
        timeout_ms,
    )
    await _click_option(page, "Run script", timeout_ms, menu=True)


def _script_dialog(page: Page) -> Locator:
    heading = page.get_by_role("heading", name="Edit Script", exact=True)
    return heading.locator('xpath=ancestor::*[@role="dialog"][1]')


async def _open_existing_script(
    page: Page, action: Locator, timeout_ms: int
) -> Locator:
    await _click(page, action, "Run a script action", timeout_ms)
    dialog = _script_dialog(page)
    if not await _visible(dialog):
        edit = page.get_by_role(
            "button", name=re.compile(r"^Edit script$", re.IGNORECASE)
        )
        await _click(page, edit, "Edit script button", timeout_ms)
    return await _one(page, dialog, "Edit Script dialog", timeout_ms)


async def _write_script(
    page: Page,
    dialog: Locator,
    script: str,
    timeout_ms: int,
    *,
    click_code_heading: bool,
) -> None:
    if click_code_heading:
        await _click(
            page,
            dialog.locator("div.strong.big.mr-auto").filter(
                has_text=re.compile(r"^Code$")
            ),
            "Code heading",
            timeout_ms,
        )
    code = await _one(
        page,
        dialog.locator('[role="code"]'),
        "script code editor",
        timeout_ms,
    )
    await code.click(timeout=timeout_ms)
    await page.keyboard.press("Control+A")
    await page.keyboard.insert_text(script)


def _script_input_row(input_name: Locator) -> Locator:
    return input_name.locator(
        'xpath=ancestor::div[.//*[@contenteditable="true"]][1]'
    )


async def _script_variable_is_correct(dialog: Locator) -> bool:
    inputs = dialog.locator(
        'input.workflowPlainTextInput[type="text"]'
    )
    if await inputs.count() != 1:
        return False
    if await inputs.input_value() != _SCRIPT_INPUT:
        return False
    return "Airtable record ID" in _text(
        await _script_input_row(inputs).inner_text()
    )


async def _configure_script_variable(
    page: Page, dialog: Locator, timeout_ms: int
) -> bool:
    await _click(
        page,
        dialog.get_by_role("heading", name="Inputs", exact=True),
        "Inputs heading",
        timeout_ms,
    )
    inputs = dialog.locator(
        'input.workflowPlainTextInput[type="text"]'
    )
    input_count = await inputs.count()
    if input_count > 1:
        raise _CandidateError(
            f"Found {input_count} script input variables; expected exactly one."
        )
    changed = False
    if input_count == 0:
        await _click(
            page,
            dialog.get_by_role("button", name="Add input variable", exact=True),
            "Add input variable",
            timeout_ms,
        )
        inputs = await _one(
            page,
            dialog.locator(
                'input.workflowPlainTextInput[type="text"]'
            ),
            "new script input name",
            timeout_ms,
        )
        changed = True
    else:
        inputs = await _one(page, inputs, "script input name", timeout_ms)

    if await inputs.input_value() != _SCRIPT_INPUT:
        await inputs.click(timeout=timeout_ms)
        await inputs.fill(_SCRIPT_INPUT, timeout=timeout_ms)
        changed = True

    row = _script_input_row(inputs)
    if "Airtable record ID" not in _text(await row.inner_text()):
        await _click(
            page,
            dialog.get_by_text("Value", exact=True),
            "input variable Value heading",
            timeout_ms,
        )
        editor = await _one(
            page,
            row.locator('.ql-editor[contenteditable="true"]'),
            "input variable value editor",
            timeout_ms,
        )
        if _text(await editor.inner_text()):
            raise _CandidateError(
                "The script input has an unexpected non-empty value; refusing "
                "to overwrite it without recorded removal clicks."
            )
        await editor.click(timeout=timeout_ms)
        plus = row.locator(
            '.object-property-lookup-button > [role="button"]'
        )
        await _click(page, plus, "script input value insert button", timeout_ms)
        builder = page.get_by_test_id("expression-builder-container")
        selectable = builder.get_by_text(
            "Airtable record ID", exact=True
        ).locator('xpath=ancestor::*[@role="button"][1]')
        await _click(
            page,
            selectable,
            "Airtable record ID value",
            timeout_ms,
        )
        changed = True

    if not await _script_variable_is_correct(dialog):
        raise _CandidateError(
            "The script input variable did not become recordId = Airtable record ID."
        )
    return changed


async def _finish_script_editor(
    page: Page, dialog: Locator, timeout_ms: int
) -> None:
    await _click(
        page,
        dialog.get_by_role("heading", name="Edit Script", exact=True),
        "Edit Script heading",
        timeout_ms,
    )
    backdrop = page.locator(
        "div.colors-background-modal-backdrop:visible"
    )
    backdrop = await _one(
        page, backdrop, "Edit Script modal backdrop", timeout_ms
    )
    await backdrop.dispatch_event("click")

    async def closed() -> bool:
        return not await _visible(dialog)

    await _wait_until(page, closed, "Edit Script dialog to close", timeout_ms)


async def _ensure_script_action(
    page: Page,
    canvas: Locator,
    script: str,
    timeout_ms: int,
    add_action: Callable[[], Awaitable[None]],
    *,
    click_code_heading: bool,
) -> tuple[bool, bool]:
    action = _workflow_action(canvas, _RUN_SCRIPT_SUMMARY)
    count = await _run_script_summaries(canvas).count()
    if count > 1:
        raise _CandidateError(
            f"Found {count} Run a script actions; refusing to choose by position."
        )
    changed = False
    new_action = count == 0
    if new_action:
        await add_action()
        dialog = await _one(
            page, _script_dialog(page), "new Edit Script dialog", timeout_ms
        )
        changed = True
    else:
        dialog = await _open_existing_script(page, action, timeout_ms)

    await _click(
        page,
        dialog.get_by_role("heading", name="Edit Script", exact=True),
        "Edit Script heading",
        timeout_ms,
    )
    # 15. Replacing the complete editor value prevents an existing action from
    # retaining unrecorded extra code.
    await _write_script(
        page,
        dialog,
        script,
        timeout_ms,
        click_code_heading=click_code_heading,
    )
    changed = True
    if await _configure_script_variable(page, dialog, timeout_ms):
        changed = True
    await _finish_script_editor(page, dialog, timeout_ms)
    return changed, True


async def _wait_for_automation_save(page: Page, timeout_ms: int) -> None:
    status = page.get_by_text("All changes saved", exact=True)

    async def saved() -> bool:
        return await status.count() == 1 and await status.is_visible()

    await _wait_until(page, saved, "automation save state", timeout_ms)


async def _apply_assignment_automation(
    page: Page,
    canvas: Locator,
    timeout_ms: int,
    verified: dict[str, bool],
) -> bool:
    changed = await _delete_assignment_update(page, canvas, timeout_ms)

    async def add_script() -> None:
        await _add_assignment_script(page, canvas, timeout_ms)

    script_changed, verified["script"] = await _ensure_script_action(
        page,
        canvas,
        _ASSIGNMENT_SCRIPT,
        timeout_ms,
        add_script,
        click_code_heading=False,
    )
    changed = changed or script_changed
    if changed:
        await _click(
            page,
            page.get_by_role("button", name="Update", exact=True),
            "automation Update button",
            timeout_ms,
        )

        unpublished = page.get_by_text(
            re.compile(r"^You have unpublished changes"),
        )

        async def applied() -> bool:
            return await unpublished.count() == 0 or not await unpublished.is_visible()

        await _wait_until(page, applied, "live automation update", timeout_ms)
    await _wait_for_automation_save(page, timeout_ms)
    return changed


async def _validate_assignment_automation(
    canvas: Locator, verified: dict[str, bool]
) -> bool:
    return (
        verified.get("script", False)
        and await _workflow_action(canvas, _OLD_ASSIGNMENT_ACTION).count() == 0
        and await _run_script_summaries(canvas).count() == 1
    )


async def _configure_assignment_automation(
    page: Page,
    report: ActionReport,
    canvas: Locator,
    timeout_ms: int,
) -> bool:
    verified: dict[str, bool] = {"script": False}
    item = "Replace status update with validated Run a script action"

    async def apply(_: str) -> bool:
        return await _apply_assignment_automation(
            page, canvas, timeout_ms, verified
        )

    async def validate(_: str) -> bool:
        return await _validate_assignment_automation(canvas, verified)

    return await _run_validated_section(
        page,
        report,
        _ASSIGNMENT_AUTOMATION,
        (item,),
        apply,
        validate,
        timeout_ms,
        retries=0,
    )


async def _automation_enabled(page: Page, timeout_ms: int) -> bool:
    toggle = await _one(
        page,
        page.get_by_role("checkbox"),
        "automation ON/OFF checkbox",
        timeout_ms,
    )
    return (await toggle.get_attribute("aria-checked")) == "true"


async def _enable_reset_automation(page: Page, timeout_ms: int) -> bool:
    if await _automation_enabled(page, timeout_ms):
        return False
    name = page.get_by_test_id("workflowName").filter(
        has_text=_RESET_AUTOMATION_TEXT
    ).locator('xpath=ancestor::*[@role="button"][1]')
    await _click(page, name, "reset automation name control", timeout_ms)
    toggle = await _one(
        page,
        page.get_by_role("checkbox"),
        "reset automation ON/OFF checkbox",
        timeout_ms,
    )
    if await toggle.get_attribute("aria-checked") != "false":
        raise _CandidateError("Reset automation toggle was not in the recorded OFF state.")
    await toggle.click(timeout=timeout_ms)

    async def enabled() -> bool:
        return await _automation_enabled(page, timeout_ms)

    await _wait_until(page, enabled, "reset automation to turn on", timeout_ms)
    return True


async def _configure_reset_automation(
    page: Page,
    report: ActionReport,
    canvas: Locator,
    timeout_ms: int,
) -> bool:
    items = ("Validated Run a script action", "Automation enabled")
    verified: dict[str, bool] = {"script": False}

    async def add_script() -> None:
        await _add_reset_script(page, canvas, timeout_ms)

    async def apply(item: str) -> bool:
        if item == items[0]:
            changed, verified["script"] = await _ensure_script_action(
                page,
                canvas,
                _RESET_SCRIPT,
                timeout_ms,
                add_script,
                click_code_heading=False,
            )
            return changed
        return await _enable_reset_automation(page, timeout_ms)

    async def validate(item: str) -> bool:
        if item == items[0]:
            return (
                verified.get("script", False)
                and await _run_script_summaries(canvas).count() == 1
            )
        return await _automation_enabled(page, timeout_ms)

    complete = await _run_validated_section(
        page,
        report,
        _RESET_AUTOMATION,
        items,
        apply,
        validate,
        timeout_ms,
        save_waiter=_wait_for_automation_save,
        retries=0,
    )
    return complete
