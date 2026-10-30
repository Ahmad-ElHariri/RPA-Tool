"""Remove the single Adsets Metrics sync source through the recorded menus.

User contract for this workflow only: multiple sources fail. Always attempt the
recorded removal path; do not infer sync state or skip. Submit Remove once,
wait five seconds, and do not verify or reload.
Evidence: PH4---Walmart__page__recording  -  10-23__10.42 (2).json, plus the
user-confirmed right-click omitted by the ordinary-click recorder.
"""

from __future__ import annotations

import logging
import re

from playwright.async_api import Locator, Page

from Backend.helpers import ActionReport, CandidateResult, Outcome, _CandidateError, _new_report
from Backend.config import Settings, lebanon_now
from Backend.helpers import _click, _one, _text, _wait_until


LOGGER = logging.getLogger(__name__)
_TABLE = "Adsets Metrics"
_CONVERSION = "Are you sure you want to convert this table to an unsynced table?"
_RETAIN_DATA = (
    "The data in this table will remain, but changes will no longer be synced. "
    "This action is not reversible."
)


# 1. Scope popups through their actual owners, preserving app-specific IDs.
def _owned_popup(page: Page, owner_id: str) -> Locator:
    if not owner_id:
        raise _CandidateError("The popup owner has no ID; cannot identify its menu.")
    escaped = owner_id.replace("\\", "\\\\").replace('"', '\\"')
    return page.locator(f'[role="dialog"][data-element-owned-by="{escaped}"]')


def _observe(page: Page, details: dict, state: str) -> None:
    details.update(last_observed_state=state, last_observed_url=page.url,
                   last_observed_at=lebanon_now().isoformat())


async def _open_table_menu(page: Page, timeout_ms: int, details: dict) -> Locator:
    table = await _one(page, page.get_by_test_id("tableTab-adsetsMetrics"),
                       "Adsets Metrics table container", timeout_ms, enabled=False)
    tab = table.get_by_role("tab", name=_TABLE, exact=True)
    await _click(page, tab, "Adsets Metrics table tab", timeout_ms)
    details["actions"].append("Selected Adsets Metrics")
    # Preserve both the recorded selection and the user-confirmed right-click.
    tab = await _one(page, tab, "Adsets Metrics table tab", timeout_ms)
    await tab.scroll_into_view_if_needed(timeout=timeout_ms)
    await tab.click(button="right", timeout=timeout_ms)
    details["actions"].append("Right-clicked Adsets Metrics")
    menu = _owned_popup(page, await table.get_attribute("id") or "").get_by_role("menu")
    menu = await _one(page, menu, "Adsets Metrics table menu", timeout_ms)
    await _one(page, menu.get_by_role("menuitem", name="Rename table", exact=True),
               "loaded table menu", timeout_ms)
    return menu


async def _single_source(page: Page, dialog: Locator, timeout_ms: int, details: dict) -> Locator:
    sources = dialog.get_by_test_id("syncSourceInfoMenu")

    async def loaded() -> bool:
        return await dialog.get_by_test_id("loading-spinner").count() == 0 and await sources.count() > 0

    await _wait_until(page, loaded, "complete sync source list", timeout_ms)
    state = _text(await dialog.inner_text())
    details["before_state"] = state
    _observe(page, details, state)
    active = re.search(r"\bActive\s*(\d+)\b", state)
    count = await sources.count()
    details.update(source_count=count, active_source_count=int(active[1]) if active else None)
    # Count the full source list; never choose its first row or remove a subset.
    if count > 1 or (active and int(active[1]) > 1):
        raise _CandidateError(
            f"Multiple sync sources: {count} source menus, "
            f"{active[1] if active else 'unknown'} active. No source was removed."
        )
    if count != 1 or active is None or int(active[1]) != 1:
        raise _CandidateError("Cannot establish exactly one active sync source; no source was removed.")
    return await _one(page, sources, "single sync source menu button", timeout_ms)


# 2. Surface observed state and the scoped verification exception in Excel messages.
def _finish(page: Page, report: ActionReport, outcome: Outcome, message: str, details: dict) -> ActionReport:
    details["diagnostic_logs"] = [handler.baseFilename for handler in logging.getLogger().handlers
                                  if isinstance(handler, logging.FileHandler)]
    lines = [message, f"Before: {details['before_state']}",
             "Actions: " + ("; ".join(details["actions"]) or "None"),
             f"Last observed: {details['last_observed_state']}",
             f"Observed at (Lebanon): {details['last_observed_at']}",
             f"URL: {details['last_observed_url']}",
             "Final state: unverified; post-action verification waived for this workflow only.",
             f"Remaining required steps: {', '.join(details['remaining_steps']) or 'None'}"]
    if details["diagnostic_logs"]:
        lines.append("Diagnostics: " + "; ".join(details["diagnostic_logs"]))
    report.results.append(CandidateResult(_TABLE, outcome, "\n".join(lines), details))
    return report.finish(page)


# 3. Submit the recorded operation once and preserve the five-second wait.
async def unsync_adsets_metrics(page: Page, settings: Settings) -> ActionReport:
    action_name = 'unsync_adsets_metrics'
    report = _new_report(action_name, page)
    timeout_ms = settings.browser_timeout_ms
    details = {
        "before_state": "Unobserved", "actions": [], "stage": "table menu",
        "post_action_verification": "Waived by user for this workflow only",
        "final_state_verified": False, "removal_submission_attempted": False,
        "wait_after_remove_seconds": 5, "wait_completed": False,
        "remaining_steps": ["open sync settings", "check single source", "remove source", "confirm Remove", "wait 5 seconds"],
    }
    _observe(page, details, "Initial page; table sync state not yet observed")
    try:
        menu = await _open_table_menu(page, timeout_ms, details)
        details["before_state"] = "Adsets Metrics table menu: " + _text(await menu.inner_text())
        _observe(page, details, details["before_state"])
        configure = menu.get_by_role("menuitem", name="Update sync configuration", exact=True)
        details["stage"] = "Update sync configuration"
        await _click(page, configure, "Update sync configuration", timeout_ms)
        details["actions"].append("Opened Update sync configuration")
        details["remaining_steps"].remove("open sync settings")
        details["stage"] = "sync settings"
        dialog = page.get_by_role("dialog").filter(
            has=page.get_by_test_id("dialogStepTitle").filter(has_text=re.compile(r"^Synced table settings$"))
        )
        dialog = await _one(page, dialog, "Synced table settings dialog", timeout_ms, enabled=False)
        source = await _single_source(page, dialog, timeout_ms, details)
        details["remaining_steps"].remove("check single source")
        details["stage"] = "source menu"
        await _click(page, source, "single sync source menu", timeout_ms)
        details["actions"].append("Opened the single source menu")
        source_menu = _owned_popup(page, await source.get_attribute("id") or "").get_by_role("menu")
        details["stage"] = "Remove source"
        await _click(page, source_menu.get_by_role("menuitem", name="Remove source", exact=True), "Remove source", timeout_ms)
        details["actions"].append("Clicked Remove source")
        details["remaining_steps"].remove("remove source")

        # The recorded confirmation has no dialog role: use its exact heading
        # and retained-data explanation to scope the final Remove control.
        details["stage"] = "removal confirmation"
        heading = await _one(page, page.get_by_text(_CONVERSION, exact=True), "convert-to-unsynced confirmation", timeout_ms, enabled=False)
        confirmation = heading.locator("xpath=..").filter(has=page.get_by_text(_RETAIN_DATA, exact=True))
        confirmation = await _one(page, confirmation, "retain-data conversion confirmation", timeout_ms, enabled=False)
        _observe(page, details, _text(await confirmation.inner_text()))
        details["stage"] = "final Remove submission"
        button = await _one(page, confirmation.get_by_role("button", name="Remove", exact=True), "final Remove confirmation", timeout_ms)
        await button.scroll_into_view_if_needed(timeout=timeout_ms)
        details["removal_submission_attempted"] = True
        await button.click(timeout=timeout_ms)
        details["actions"].append("Clicked final Remove once")
        details["remaining_steps"].remove("confirm Remove")
        details["stage"] = "five-second wait"
        await page.wait_for_timeout(5_000)
        details["wait_completed"] = True
        details["actions"].append("Waited 5 seconds")
        details["remaining_steps"].remove("wait 5 seconds")
        details["stage"] = "completed without final-state verification"
        return _finish(page, report, Outcome.SUCCESS,
                       "Removal submitted once; completed the 5-second wait. Resulting table state unverified by request.", details)
    except Exception as exc:
        LOGGER.exception("Adsets Metrics unsync failed at %s", details["stage"])
        message = f"Failed at {details['stage']}: {type(exc).__name__}: {exc}"
        if details["removal_submission_attempted"]:
            message += " Final Remove was attempted; its effect is unknown. It was not retried."
        return _finish(page, report, Outcome.FAILED, message, details)
