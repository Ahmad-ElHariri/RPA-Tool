"""Update Media Plan's Campaign Duration and Campaign Completion formulas.

Evidence: Nestle__page__recording  -  11-02__17.55.json (all 11 clicks),
plus the user's exact formulas and 2026-11-02 approval of exact-match skips
and P&G development trials. Preserve the Duration -> Completion edit order,
Save and dependency Confirm change. The recording's Completion double-click
opens the same Field customization editor; use the explicit column menu path
for both fields so separate clicks can each receive the required three seconds.

Preflight both existing Formula fields before edits. Never retry submissions,
recover drafts, change formatting or modify records. Validate the whole section
after reload using the shared validator with zero retries. Stop further actions
after a failure; a partial save is reported, never silently resubmitted.
"""

from __future__ import annotations

import json
import logging
import re

from playwright.async_api import Locator, Page

from Backend.config import Settings, artifact_path, lebanon_now
from Backend.helpers import (
    ActionReport, Outcome, _CandidateError, _new_report, _one,
    _run_validated_section, _text, _wait_until,
)
from Backend.workflows.multiple_target_market_core import (
    _after_action, _click_step, _read_formula,
)


LOGGER = logging.getLogger(__name__)
_IMPACT = re.compile(r"^Changing this field[\u2019']s configuration will impact \d+ dependenc(?:y|ies)\.$")
DURATION_FORMULA = """IF(
  AND({Start Date}, {End Date}),
  DATETIME_DIFF({End Date}, {Start Date}, 'days') + 1,
  BLANK()
)"""
COMPLETION_FORMULA = '''IF(
  AND({Start Date}, {End Date}),
  IF(
    DATETIME_DIFF(
      DATETIME_PARSE(ARRAYJOIN({End Date}, "")),
      DATETIME_PARSE(ARRAYJOIN({Start Date}, "")),
      'days'
    ) < 0,
    0,
    MIN(
      1,
      ROUND(
        MAX(
          0,
          DATETIME_DIFF(
            TODAY(),
            DATETIME_PARSE(ARRAYJOIN({Start Date}, "")),
            'days'
          ) + 1
        ) /
        (
          DATETIME_DIFF(
            DATETIME_PARSE(ARRAYJOIN({End Date}, "")),
            DATETIME_PARSE(ARRAYJOIN({Start Date}, "")),
            'days'
          ) + 1
        ),
        2
      )
    )
  ),
  0
)'''
FORMULAS = {"Campaign Duration": DURATION_FORMULA, "Campaign Completion": COMPLETION_FORMULA}


# 1. Keep field identity, observable state and dialog ownership explicit.
async def _observe(page: Page, details: dict, state: str) -> None:
    details.update(last_observed_state=state, last_observed_url=page.url,
                   last_observed_at=lebanon_now().isoformat())
    # Record only visible status evidence, never infer save state from a click.
    statuses = await page.get_by_role("status").evaluate_all("""nodes => nodes
        .filter(n => n.getClientRects().length && getComputedStyle(n).visibility !== 'hidden')
        .map(n => n.innerText.trim()).filter(Boolean)""")
    details["last_observed_airtable_status"] = " | ".join(statuses) or "Unobserved: no visible Airtable status text"


async def _guard_dialogs(page: Page, *, editor: bool = False,
                         menu: bool = False, confirmation: bool = False) -> None:
    unexpected = await page.get_by_role("dialog").evaluate_all(r"""(nodes, allow) => {
        const help = [
            'Examples: Amount * Price AVERAGE(field1, field2) Name & "-" & Date IF(Price * Quantity > 5, "Yes", "No")',
            "DATETIME_DIFF(From, To, units) Returns the difference between datetimes in specified units. Example: DATETIME_DIFF({Deadline}, TODAY(), 'weeks')"
        ];
        const expected = n => {
            const text = n.innerText.replace(/\s+/g, ' ').trim();
            if (allow.editor && n.getAttribute('aria-label') === 'Field customization') return true;
            if (allow.editor && (help.includes(text) || /^IF\(logical, value1, value2\)/.test(text))) return true;
            if (allow.menu && n.querySelector('[role="menu"] [data-tutorial-selector-id="columnMenuItem-changeType"]')) return true;
            return allow.confirmation && Array.from(n.querySelectorAll('h2')).some(h =>
                /^Changing this field[\u2019']s configuration will impact \d+ dependenc(?:y|ies)\.$/.test(h.textContent.trim()));
        };
        return nodes.filter(n => n.getClientRects().length && getComputedStyle(n).visibility !== 'hidden')
            .filter(n => !expected(n) && !Array.from(n.querySelectorAll('[role="dialog"]')).some(expected))
            .map(n => n.innerText);
    }""", {"editor": editor, "menu": menu, "confirmation": confirmation})
    if unexpected:
        raise _CandidateError("Unexpected dialog: " + " | ".join(unexpected))


def _header(page: Page, field: str) -> Locator:
    return page.locator('[data-tutorial-selector-id="gridHeaderCell"]').filter(
        has=page.get_by_label(f"{field} column header (Formula field)", exact=True))


async def _open_table(page: Page, timeout_ms: int, details: dict) -> None:
    await _guard_dialogs(page)
    table = page.get_by_test_id("tableTab-mediaPlan")
    tab = table.get_by_role("tab", name="Media Plan", exact=True)
    await _click_step(page, tab, "Open Media Plan", timeout_ms, details)
    async def selected() -> bool:
        return await tab.get_attribute("aria-selected") == "true"
    await _wait_until(page, selected, "Media Plan tab selected", timeout_ms)
    owner = await table.get_attribute("id")
    if owner:
        escaped = owner.replace("\\", "\\\\").replace('"', '\\"')
        menu = page.locator(f'[role="dialog"][data-element-owned-by="{escaped}"]').get_by_role("menu")
        if await menu.count():
            await _one(page, menu.get_by_role("menuitem", name="Rename table", exact=True),
                       "owned Media Plan menu", timeout_ms)
            await page.keyboard.press("Escape")
            await _after_action(page, details, "Dismiss owned Media Plan table menu")
            await menu.wait_for(state="hidden", timeout=timeout_ms)
    await _guard_dialogs(page)
    await _observe(page, details, "Media Plan selected; grid accessible")


async def _reveal_header(page: Page, field: str, timeout_ms: int, details: dict) -> None:
    details.update(stage=f"Reveal {field}", expected_state=f"Unique visible {field} Formula header")
    header = await _one(page, _header(page, field), f"{field} Formula header", timeout_ms)
    delta = await header.evaluate("""n => {
        const r = n.getBoundingClientRect(), c = n.closest('[data-visibility-clip-x]')?.getBoundingClientRect();
        const left = Math.max(0, c?.left ?? 0), right = Math.min(innerWidth, c?.right ?? innerWidth);
        return r.left >= left && r.right <= right ? 0 : (r.left + r.right - left - right) / 2;
    }""")
    if delta:
        grid = await _one(page, page.get_by_role("application", name=
            "Use Enter to explore the contents of this grid, and Escape when you're finished", exact=True),
            "Media Plan horizontal grid scroller", timeout_ms)
        await grid.evaluate("(n, delta) => {n.scrollLeft += delta;}", delta)
        await _after_action(page, details, f"Scroll to {field}")
    async def in_view() -> bool:
        return await header.evaluate("""n => {
            const r = n.getBoundingClientRect(), c = n.closest('[data-visibility-clip-x]')?.getBoundingClientRect();
            return r.width > 0 && r.left >= Math.max(0, c?.left ?? 0) &&
                r.right <= Math.min(innerWidth, c?.right ?? innerWidth);
        }""")
    await _wait_until(page, in_view, f"{field} header within visible grid bounds", timeout_ms)


async def _open_editor(page: Page, field: str, timeout_ms: int, details: dict) -> Locator:
    await _guard_dialogs(page)
    await _reveal_header(page, field, timeout_ms, details)
    title = page.get_by_label(f"{field} column header (Formula field)", exact=True)
    await _click_step(page, title, f"Click {field}", timeout_ms, details)
    async def selected() -> bool:
        return "selected" in (await _header(page, field).get_attribute("class") or "").split()
    await _wait_until(page, selected, f"{field} column selected", timeout_ms)
    await _guard_dialogs(page)
    await _click_step(page, title, f"Right-click {field}", timeout_ms, details, button="right")
    menu = page.get_by_role("menu").filter(has=page.get_by_role("menuitem", name="Edit field", exact=True))
    await _one(page, menu, f"{field} column menu", timeout_ms)
    await _guard_dialogs(page, menu=True)
    await _click_step(page, menu.get_by_role("menuitem", name="Edit field", exact=True),
                      f"Edit {field}", timeout_ms, details)
    dialog = await _one(page, page.get_by_role("dialog", name="Field customization", exact=True),
                        "field customization", timeout_ms)
    await _guard_dialogs(page, editor=True)
    name = await _one(page, dialog.get_by_role("textbox", name="Field name (optional)", exact=True),
                      "edited field name", timeout_ms)
    kind = await _one(page, dialog.locator('[role="button"][aria-label="Field type"]'),
                      "edited field type", timeout_ms)
    if await name.input_value() != field or _text(await kind.inner_text()) != "Formula":
        raise _CandidateError(f"Editor does not identify {field} as a Formula field; no edit attempted.")
    await _observe(page, details, f"Editor identifies {field}, type Formula")
    return dialog


async def _close_editor(page: Page, dialog: Locator, timeout_ms: int, details: dict) -> None:
    await _click_step(page, dialog.get_by_role("button", name="Cancel", exact=True),
                      "Close field editor without submission", timeout_ms, details)
    await dialog.wait_for(state="hidden", timeout=timeout_ms)
    await _guard_dialogs(page)


# 2. Replace complete text only after preflight and verify before each submission.
async def _replace_formula(page: Page, dialog: Locator, formula: str,
                           timeout_ms: int, details: dict) -> None:
    editor = dialog.locator('[aria-label="Formula input"][data-mode-id="airtableFormulas"]')
    await _guard_dialogs(page, editor=True)
    if not await editor.evaluate("n => n.contains(n.ownerDocument.activeElement)"):
        raise _CandidateError("Formula editor lost focus; no clearing attempted.")
    details.update(stage="Clear old formula", expected_state="Empty formula editor")
    await page.keyboard.press("Backspace")
    await _after_action(page, details, "Clear old formula")
    # Monaco's copy-line-when-selection-is-empty path may include a newline
    # for its single empty line. Whitespace contains no formula to preserve.
    cleared = await _read_formula(page, dialog, timeout_ms, details)
    details["cleared_formula"] = cleared
    details.update(stage="Verify cleared formula", expected_state="No non-whitespace formula text")
    if cleared.strip():
        raise _CandidateError("Old formula remains after clearing; replacement not pasted.")
    details["remaining_steps"].remove("clear old formula")
    details.update(stage="Paste new formula", expected_state="Exact supplied formula in the editor")
    await _guard_dialogs(page, editor=True)
    await editor.evaluate("""(n, text) => {
        const active = n.ownerDocument.activeElement;
        if (!n.contains(active)) throw new Error('Formula editor lost focus');
        const transfer = new DataTransfer(); transfer.setData('text/plain', text);
        const event = new ClipboardEvent('paste', {bubbles:true, cancelable:true, clipboardData:transfer});
        active.dispatchEvent(event);
        if (!event.defaultPrevented) throw new Error('Editor did not handle paste');
    }""", formula)
    await _after_action(page, details, "Paste exact supplied formula")
    entered = await _read_formula(page, dialog, timeout_ms, details)
    details["entered_formula"] = entered
    if entered != formula:
        raise _CandidateError("Formula read-back differs from supplied text; Save not attempted.")
    details["remaining_steps"].remove("paste new formula")
    await _observe(page, details, "Exact replacement formula read back before Save")
    await _guard_dialogs(page, editor=True)
    await _click_step(page, dialog.get_by_role("button", name="Save", exact=True),
                      "Save", timeout_ms, details, submission="save_attempted")
    details.update(stage="Verify dependency confirmation", expected_state="Recorded dependency confirmation")
    confirmation = await _one(page, page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name=_IMPACT)), "field dependency confirmation", timeout_ms)
    details["dependency_confirmation"] = _text(await confirmation.inner_text())
    details["remaining_steps"].remove("Save")
    await _observe(page, details, details["dependency_confirmation"])
    await _guard_dialogs(page, editor=True, confirmation=True)
    await _click_step(page, confirmation.get_by_role("button", name="Confirm change", exact=True),
                      "Confirm change", timeout_ms, details, submission="confirmation_attempted")
    details.update(stage="Verify save completion", expected_state="Confirmation and field editor closed")
    await confirmation.wait_for(state="hidden", timeout=timeout_ms)
    await dialog.wait_for(state="hidden", timeout=timeout_ms)
    await _guard_dialogs(page)
    details["remaining_steps"].remove("Confirm change")
    await _observe(page, details, "Save and confirmation completed; reload persistence still pending")


async def _capture_failure(page: Page, settings: Settings, details: dict, exc: Exception) -> None:
    LOGGER.error("Campaign duration failed at %s", details["stage"], exc_info=(type(exc), exc, exc.__traceback__))
    details["error"] = f"{type(exc).__name__}: {exc}"
    try:
        dialogs = await page.get_by_role("dialog").all_inner_texts()
        await _observe(page, details, " | ".join(dialogs) if dialogs else details["error"])
        dom = {"url": page.url, "stage": details["stage"],
               "headers": await page.locator('[data-tutorial-selector-id="gridHeaderCell"]').evaluate_all(
                   "nodes => nodes.map(n => n.outerHTML)"),
               "dialogs": await page.get_by_role("dialog").evaluate_all("nodes => nodes.map(n => n.outerHTML)")}
        path = artifact_path(settings.logs_dir, "campaign_duration DOM", ".json")
        path.write_text(json.dumps(dom, indent=2, ensure_ascii=False), encoding="utf-8")
        details["diagnostic_dom"] = str(path)
        LOGGER.info("Formula diagnostics: %s", path)
    except Exception:
        LOGGER.exception("Could not capture final campaign formula DOM")


# 3. Validate both fields as one section, without retries or actions after failure.
async def campaign_duration(page: Page, settings: Settings) -> ActionReport:
    """Update both campaign formulas once, or skip exact matches; verify after reload."""
    report = _new_report("campaign_duration", page)
    timeout_ms = settings.browser_timeout_ms
    states = {field: {
        "before_state": "Unobserved", "actions": [], "verification": [],
        "stage": "Preflight", "expected_state": f"Existing {field} Formula field",
        "save_attempted": False, "confirmation_attempted": False, "reload_verified": False,
        "last_observed_state": "Unobserved", "last_observed_url": page.url,
        "last_observed_at": lebanon_now().isoformat(), "last_observed_airtable_status": "Unobserved",
        "remaining_steps": ["read current formula", "clear old formula", "paste new formula",
                            "Save", "Confirm change", "verify reload persistence"],
    } for field in FORMULAS}
    workflow = {"actions": [], "stage": "Initial navigation", "expected_state": "Media Plan ready"}
    blocked = False
    reloaded = False
    current_details = workflow

    try:
        await _after_action(page, workflow, "Wait after initial target navigation")
        await _open_table(page, timeout_ms, workflow)
        for field, details in states.items():
            current_details = details
            dialog = await _open_editor(page, field, timeout_ms, details)
            before = await _read_formula(page, dialog, timeout_ms, details)
            details.update(before_formula=before, before_state="Complete original formula captured from named Formula field")
            details["remaining_steps"].remove("read current formula")
            if before == FORMULAS[field]:
                details["skip_reason"] = "Complete existing formula exactly matches the supplied formula"
                details["remaining_steps"] = ["verify reload persistence"]
            await _close_editor(page, dialog, timeout_ms, details)
            await _observe(page, details, "Original formula captured; preflight editor closed without submission")
    except Exception as exc:
        blocked = True
        await _capture_failure(page, settings, current_details, exc)
        for details in states.values():
            details["error"] = current_details["error"]
            details["stage"] = current_details["stage"]
            details["expected_state"] = current_details["expected_state"]

    async def apply(field: str) -> bool:
        nonlocal blocked
        details = states[field]
        if blocked:
            raise _CandidateError("Workflow stopped; no further field actions attempted.")
        if "skip_reason" in details:
            return False
        try:
            dialog = await _open_editor(page, field, timeout_ms, details)
            current = await _read_formula(page, dialog, timeout_ms, details)
            if current != details["before_formula"]:
                raise _CandidateError("Formula changed since preflight; no replacement attempted.")
            await _replace_formula(page, dialog, FORMULAS[field], timeout_ms, details)
            return True
        except Exception as exc:
            blocked = True
            await _capture_failure(page, settings, details, exc)
            raise _CandidateError(details["error"]) from exc

    async def reload_section(page: Page, timeout_ms: int) -> None:
        nonlocal blocked, reloaded
        workflow.update(stage="Reload Media Plan", expected_state="Both formulas persist after reload")
        try:
            await page.reload(wait_until="domcontentloaded", timeout=settings.navigation_timeout_ms)
            await _after_action(page, workflow, "Reload for both-formula verification")
            await _open_table(page, timeout_ms, workflow)
            reloaded = True
        except Exception as exc:
            blocked = True
            await _capture_failure(page, settings, workflow, exc)
            raise _CandidateError(workflow["error"]) from exc

    async def validate(field: str) -> bool:
        nonlocal blocked
        details = states[field]
        if blocked or not reloaded:
            return False
        try:
            dialog = await _open_editor(page, field, timeout_ms, details)
            after = await _read_formula(page, dialog, timeout_ms, details)
            details["after_formula"] = after
            details.update(stage="Verify reloaded formula", expected_state="Exact supplied formula after reload")
            if after != FORMULAS[field]:
                raise _CandidateError("Reloaded formula differs from supplied text; no submission repeated.")
            details["reload_verified"] = True
            details["verification"].append("Complete formula exactly matches supplied text after reload")
            await _close_editor(page, dialog, timeout_ms, details)
            details["remaining_steps"] = []
            await _observe(page, details, "Exact formula verified after reload; verification editor closed without submission")
            return True
        except Exception as exc:
            blocked = True
            await _capture_failure(page, settings, details, exc)
            raise _CandidateError(details["error"]) from exc

    await _run_validated_section(page, report, "Media Plan campaign formulas", tuple(FORMULAS),
                                 apply, validate, timeout_ms, save_waiter=reload_section, retries=0)
    logs = [h.baseFilename for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler)]
    for result, (field, details) in zip(report.results, states.items()):
        details.update(diagnostic_logs=logs, workflow_actions=workflow["actions"])
        if "error" in workflow:
            details["workflow_error"] = workflow["error"]
            details["workflow_diagnostic_dom"] = workflow.get("diagnostic_dom", "Unavailable")
        result.details.update(details)
        result.message = "\n".join([
            result.message, f"Before: {details['before_state']}",
            "Actions: " + ("; ".join(a["step"] for a in details["actions"]) or "None"),
            "Skip: " + details.get("skip_reason", "Not skipped"),
            "Verification: " + ("; ".join(details["verification"]) or "Not completed"),
            "Reason: " + details.get("error", workflow.get("error", "No error")),
            f"Step: {details['stage']}; expected: {details['expected_state']}",
            f"Last observed: {details['last_observed_state']}",
            f"Airtable status: {details['last_observed_airtable_status']}",
            f"Observed at (Lebanon): {details['last_observed_at']}", f"URL: {details['last_observed_url']}",
            "Remaining required steps: " + (", ".join(details["remaining_steps"]) or "None"),
            "Diagnostics: " + ("; ".join(logs) or "Unavailable"),
        ])
    if report.ok and all("skip_reason" in d for d in states.values()):
        report.results[-1].outcome = Outcome.SKIPPED
    report.results[-1].details.update(workflow_actions=workflow["actions"], diagnostic_logs=logs)
    return report.finish(page)
