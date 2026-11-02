"""Replace Media Plan's Core Completion Status formula through the recorded UI.

Contract: select Media Plan, click the formula column, then right-click it and
choose Edit field. Preserve the supplied formula exactly. An exact existing
match skips the write. Otherwise clear, paste, Save once, Confirm change once,
and verify the full formula after reload. Every action has a three-second wait;
existing workflows are unaffected. No submission or partial write is retried.
Evidence: PH0__page__recording  -  10-30__17.29.json, all six clicks, plus the
user-confirmed right-click, formula text, and explicit click-before-right-click.
"""

from __future__ import annotations

import logging
import json
import re

from playwright.async_api import Locator, Page

from Backend.config import Settings, artifact_path, lebanon_now
from Backend.helpers import (
    ActionReport, CandidateResult, Outcome, _CandidateError, _new_report,
    _one, _text, _wait_until,
)


LOGGER = logging.getLogger(__name__)
_FIELD = "Core Completion Status"
_ACTION_WAIT_MS = 3_000
_IMPACT = re.compile(r"^Changing this field[’']s configuration will impact \d+ dependenc(?:y|ies)\.$")
FORMULA = '''IF(
  {Track Core Campaign Progress} != "",
  IF(
    OR(
      NOT({Campaign Name Reference}),
      NOT({Platform}),
      NOT({Market}),
      NOT({Buying Model}),
      NOT({Budget}),
      NOT({Start Date}),
      NOT({End Date}),
      AND({Buying Model} = "CPM", NOT({CPM})),
      AND({Buying Model} = "CPC", NOT({CPC})),
      AND({Buying Model} = "CPV", NOT({CPV})),
      AND({Buying Model} = "CPA", NOT({CPA})),
      {Start Date} < {Proposed Start Date (from Brief)},
      {End Date} > {Proposed End Date (from Brief)},
      AND({Start Date}, {End Date}, {End Date} <= {Start Date}),
      AND(
        {Market},
        {Target Market (from Brief)},
        NOT(
          OR(
            SEARCH(", " & {Market} & ",", ", " & {Target Market (from Brief)} & ","),
            SEARCH("," & {Market} & ",", "," & {Target Market (from Brief)} & ",")
          )
        )
      )
    ),
    "⚠️ Missing or invalid fields: " &
    LEFT(
      IF(NOT({Campaign Name Reference}), "Campaign Name, ", "") &
      IF(NOT({Platform}), "Platform, ", "") &
      IF(NOT({Market}), "Market, ", "") &
      IF(NOT({Buying Model}), "Buying Model, ", "") &
      IF(NOT({Budget}), "Budget, ", "") &
      IF(NOT({Start Date}), "Start Date, ", "") &
      IF(NOT({End Date}), "End Date, ", "") &
      IF(AND({Buying Model} = "CPM", NOT({CPM})), "CPM (required), ", "") &
      IF(AND({Buying Model} = "CPC", NOT({CPC})), "CPC (required), ", "") &
      IF(AND({Buying Model} = "CPV", NOT({CPV})), "CPV (required), ", "") &
      IF(AND({Buying Model} = "CPA", NOT({CPA})), "CPA (required), ", "") &
      IF({Start Date} < {Proposed Start Date (from Brief)}, "Start Date before Proposed Start, ", "") &
      IF({End Date} > {Proposed End Date (from Brief)}, "End Date after Proposed End, ", "") &
      IF(AND({Start Date}, {End Date}, {End Date} <= {Start Date}), "End Date must be after Start Date, ", "") &
      IF(
        AND(
          {Market},
          {Target Market (from Brief)},
          NOT(
            OR(
              SEARCH(", " & {Market} & ",", ", " & {Target Market (from Brief)} & ","),
              SEARCH("," & {Market} & ",", "," & {Target Market (from Brief)} & ",")
            )
          )
        ),
        "Market not in Target Market list, ",
        ""
      ),
      1000
    ),
    ""
  )
)'''


# 1. Keep action delays and evidence local to this workflow.
def _observe(page: Page, details: dict, state: str) -> None:
    details.update(last_observed_state=state, last_observed_url=page.url,
                   last_observed_at=lebanon_now().isoformat())


async def _after_action(page: Page, details: dict, name: str) -> None:
    action = {"step": name, "wait_seconds": _ACTION_WAIT_MS / 1000, "wait_completed": False}
    details["actions"].append(action)
    LOGGER.info("%s; waiting %g seconds", name, action["wait_seconds"])
    await page.wait_for_timeout(_ACTION_WAIT_MS)
    action["wait_completed"] = True


async def _click_step(page: Page, target: Locator, name: str, timeout_ms: int,
                      details: dict, *, button: str = "left", submission: str = "") -> None:
    details.update(stage=name, expected_state=f"One visible, enabled {name} control")
    target = await _one(page, target, name, timeout_ms)
    if await target.get_attribute("aria-busy") == "true" or await target.get_attribute("aria-disabled") == "true":
        raise _CandidateError(f"{name} is busy or disabled; no click attempted.")
    if submission:
        # A thrown click may already have reached Airtable. Never submit again.
        details[submission] = True
    await target.click(button=button, timeout=timeout_ms)
    await _after_action(page, details, name)


async def _guard_dialogs(page: Page, details: dict, *, editor: bool = False,
                         menu: bool = False, confirmation: bool = False) -> None:
    """Allow only the recorded popups and their ancestor dialog wrappers."""
    unexpected = await page.get_by_role("dialog").evaluate_all("""(dialogs, allow) => {
        const expected = node => {
            if (allow.editor && node.getAttribute('aria-label') === 'Field customization') return true;
            if (allow.menu && node.querySelector('[role="menu"] [data-tutorial-selector-id="columnMenuItem-changeType"]')) return true;
            if (allow.editor && /^IF\\(logical, value1, value2\\)/.test(node.innerText.trim())) return true;
            // Airtable also shows this observed, non-modal editor help after Select All.
            if (allow.editor && node.querySelector('.examples') && node.innerText.replace(/\\s+/g, ' ').trim() ===
                'Examples: Amount * Price AVERAGE(field1, field2) Name & "-" & Date IF(Price * Quantity > 5, "Yes", "No")') return true;
            return allow.confirmation && Array.from(node.querySelectorAll('h2')).some(h =>
                /^Changing this field[’']s configuration will impact \\d+ dependenc(?:y|ies)\\.$/.test(h.textContent.trim()));
        };
        return dialogs.filter(node => node.getClientRects().length && getComputedStyle(node).visibility !== 'hidden')
            .filter(node => !expected(node) && !Array.from(node.querySelectorAll('[role="dialog"]')).some(expected))
            .map(node => node.innerText);
    }""", {"editor": editor, "menu": menu, "confirmation": confirmation})
    if unexpected:
        _observe(page, details, "Unexpected dialog: " + " | ".join(unexpected))
        raise _CandidateError(details["last_observed_state"])


def _header(page: Page) -> Locator:
    return page.locator('[data-tutorial-selector-id="gridHeaderCell"]').filter(
        has=page.get_by_label(f"{_FIELD} column header (Formula field)", exact=True)
    )


async def _reveal_header(page: Page, timeout_ms: int, details: dict) -> None:
    """Scroll the observed grid container using the named header's live bounds."""
    details.update(stage="Reveal Core Completion Status", expected_state="Named formula header visible in the Media Plan grid")
    header = await _one(page, _header(page), f"{_FIELD} formula header", timeout_ms)
    delta = await header.evaluate("""node => {
        const clip = node.closest('[data-visibility-clip-x]');
        const r = node.getBoundingClientRect();
        const c = clip ? clip.getBoundingClientRect() : {left: 0, right: innerWidth};
        if (r.left >= c.left && r.right <= c.right) return 0;
        return (r.left + r.right - c.left - c.right) / 2;
    }""")
    if delta:
        grid = await _one(page, page.get_by_role("application", name=
            "Use Enter to explore the contents of this grid, and Escape when you're finished", exact=True),
            "Media Plan horizontal grid scroller", timeout_ms)
        details["stage"] = "Reveal Core Completion Status"
        await grid.evaluate("(node, delta) => { node.scrollLeft += delta; }", delta)
        await _after_action(page, details, "Scroll Media Plan to the named formula header")
    if not await header.evaluate("""node => {
        const r = node.getBoundingClientRect();
        const c = node.closest('[data-visibility-clip-x]')?.getBoundingClientRect();
        return r.width > 0 && r.left >= Math.max(0, c?.left ?? 0) &&
            r.right <= Math.min(innerWidth, c?.right ?? innerWidth);
    }"""):
        raise _CandidateError("The named formula header is off-screen; no field click attempted.")


# 2. Follow the selected table -> normal field click -> right-click -> Edit path.
async def _open_editor(page: Page, timeout_ms: int, details: dict) -> Locator:
    await _guard_dialogs(page, details)
    table = page.get_by_test_id("tableTab-mediaPlan")
    tab = table.get_by_role("tab", name="Media Plan", exact=True)
    await _click_step(page, tab, "Open Media Plan", timeout_ms, details)
    details["expected_state"] = "Media Plan tab selected"
    async def selected() -> bool:
        return await tab.get_attribute("aria-selected") == "true"
    await _wait_until(page, selected, details["expected_state"], timeout_ms)
    _observe(page, details, "Media Plan tab is selected")
    # Clicking an already-selected tab opens its own menu and hides the grid
    # from accessibility queries. Dismiss only that identified, observed menu.
    owner = await table.get_attribute("id")
    if owner:
        escaped = owner.replace("\\", "\\\\").replace('"', '\\"')
        table_menu = page.locator(f'[role="dialog"][data-element-owned-by="{escaped}"]').get_by_role("menu")
        if await table_menu.count():
            await _one(page, table_menu.get_by_role("menuitem", name="Rename table", exact=True),
                       "owned Media Plan table menu", timeout_ms)
            details.update(stage="Dismiss selected Media Plan table menu", expected_state="Owned table menu closed")
            await page.keyboard.press("Escape")
            await _after_action(page, details, "Dismiss selected Media Plan table menu")
            await table_menu.wait_for(state="hidden", timeout=timeout_ms)
            _observe(page, details, "Selected Media Plan table menu closed; grid accessible")
    await _guard_dialogs(page, details)
    await _reveal_header(page, timeout_ms, details)
    title = page.get_by_label(f"{_FIELD} column header (Formula field)", exact=True)
    await _click_step(page, title, "Click Core Completion Status", timeout_ms, details)
    details["expected_state"] = "Core Completion Status column selected"
    async def column_selected() -> bool:
        return "selected" in (await _header(page).get_attribute("class") or "").split()
    await _wait_until(page, column_selected, details["expected_state"], timeout_ms)
    _observe(page, details, "Core Completion Status formula column is selected")
    await _guard_dialogs(page, details)
    await _click_step(page, title, "Right-click Core Completion Status", timeout_ms, details, button="right")
    menu = page.get_by_role("menu").filter(has=page.get_by_role("menuitem", name="Edit field", exact=True))
    await _one(page, menu, "formula column menu", timeout_ms)
    await _guard_dialogs(page, details, menu=True)
    await _click_step(page, menu.get_by_role("menuitem", name="Edit field", exact=True),
                      "Edit field", timeout_ms, details)
    dialog = await _one(page, page.get_by_role("dialog", name="Field customization", exact=True),
                        "field customization dialog", timeout_ms)
    await _guard_dialogs(page, details, editor=True)
    field_name = await _one(page, dialog.get_by_role("textbox", name="Field name (optional)", exact=True),
                            "edited field name", timeout_ms, enabled=False)
    field_type = await _one(page, dialog.locator('[role="button"][aria-label="Field type"]'),
                            "edited field type", timeout_ms, enabled=False)
    if await field_name.input_value() != _FIELD or _text(await field_type.inner_text()) != "Formula":
        raise _CandidateError("Field customization does not identify Core Completion Status as a Formula field.")
    _observe(page, details, "Field customization identifies Core Completion Status, type Formula")
    return dialog


async def _read_formula(page: Page, dialog: Locator, timeout_ms: int, details: dict) -> str:
    editor = await _one(page, dialog.locator('[aria-label="Formula input"][data-mode-id="airtableFormulas"]'),
                        "Formula input", timeout_ms)
    await _click_step(page, editor.get_by_role("code"), "Focus formula editor", timeout_ms, details)
    if not await editor.evaluate("node => node.contains(node.ownerDocument.activeElement)"):
        raise _CandidateError("Keyboard focus is outside the formula editor.")
    details["stage"] = "Select complete formula"
    await page.keyboard.press("Control+A")
    await _after_action(page, details, "Select complete formula")
    details.update(stage="Read complete formula", expected_state="Complete plain-text selection from the focused formula editor")
    # Monaco supplies its complete selection through its normal copy handler.
    # A synthetic copy uses a local DataTransfer, never the system clipboard:
    # https://www.w3.org/TR/clipboard-apis/#clipboard-event-copy
    # Fail before clearing if the editor cannot expose the full selected text.
    copied = await editor.evaluate("""node => {
        const active = node.ownerDocument.activeElement;
        if (!node.contains(active)) throw new Error('Formula editor lost keyboard focus');
        const transfer = new DataTransfer();
        const event = new ClipboardEvent('copy', {bubbles: true, cancelable: true, clipboardData: transfer});
        active.dispatchEvent(event);
        if (!event.defaultPrevented || !Array.from(transfer.types).includes('text/plain'))
            throw new Error('The formula editor did not expose a complete plain-text selection');
        return transfer.getData('text/plain');
    }""")
    await _after_action(page, details, "Read selected formula into local verification data")
    return copied.replace("\r\n", "\n")


async def _check_editor_focus(page: Page, dialog: Locator, details: dict) -> None:
    await _guard_dialogs(page, details, editor=True)
    editor = dialog.locator('[aria-label="Formula input"][data-mode-id="airtableFormulas"]')
    if await editor.count() != 1 or not await editor.evaluate("node => node.contains(node.ownerDocument.activeElement)"):
        raise _CandidateError("Formula editor lost focus; no keyboard edit attempted.")


async def _close_editor(page: Page, dialog: Locator, timeout_ms: int, details: dict) -> None:
    await _click_step(page, dialog.get_by_role("button", name="Cancel", exact=True),
                      "Close field editor without another submission", timeout_ms, details)
    await dialog.wait_for(state="hidden", timeout=timeout_ms)
    await _guard_dialogs(page, details)


# 3. Keep before/after state, unresolved work, and diagnostic paths in Excel.
def _finish(page: Page, report: ActionReport, outcome: Outcome, message: str, details: dict) -> ActionReport:
    details["diagnostic_logs"] = [handler.baseFilename for handler in logging.getLogger().handlers
                                  if isinstance(handler, logging.FileHandler)]
    lines = [message, f"Before: {details['before_state']}",
             "Actions: " + "; ".join(action["step"] for action in details["actions"]),
             "Verification: " + ("; ".join(details["verification"]) or "Not completed"),
             f"Last observed: {details['last_observed_state']}",
             f"Airtable status: {details['last_observed_airtable_status']}",
             f"Observed at (Lebanon): {details['last_observed_at']}",
             f"URL: {details['last_observed_url']}",
             "Remaining required steps: " + (", ".join(details["remaining_steps"]) or "None")]
    if details["diagnostic_logs"]:
        lines.append("Diagnostics: " + "; ".join(details["diagnostic_logs"]))
    report.results.append(CandidateResult(f"Media Plan / {_FIELD}", outcome, "\n".join(lines), details))
    return report.finish(page)


async def multiple_target_market_core(page: Page, settings: Settings) -> ActionReport:
    """Save the exact multiple-market formula once and verify reload persistence."""
    report = _new_report("multiple_target_market_core", page)
    timeout_ms = settings.browser_timeout_ms
    details = {
        "before_state": "Unobserved", "actions": [], "verification": [],
        "stage": "initial navigation delay", "expected_state": "Loaded target page",
        "save_attempted": False, "confirmation_attempted": False,
        "reload_verified": False, "last_observed_airtable_status":
            "Unobserved: the recording identifies no Airtable save/status indicator",
        "remaining_steps": ["read current formula", "clear old formula", "paste new formula",
                            "Save", "Confirm change", "verify reload persistence"],
    }
    _observe(page, details, "Initial target page; field formula unobserved")
    try:
        # The runner navigates before dispatch; honor its navigation delay too.
        await _after_action(page, details, "Wait after initial target navigation")
        dialog = await _open_editor(page, timeout_ms, details)
        before = await _read_formula(page, dialog, timeout_ms, details)
        details.update(before_formula=before, before_state="Complete original formula read from the named field editor")
        details["remaining_steps"].remove("read current formula")
        _observe(page, details, "Original field formula captured in before_formula")
        if before == FORMULA:
            details["skip_reason"] = "The complete existing formula exactly matches the supplied formula"
            details["verification"].append(details["skip_reason"])
            await _close_editor(page, dialog, timeout_ms, details)
            details["remaining_steps"] = []
            _observe(page, details, "Exact existing formula verified; editor closed without Save or Confirm change")
            return _finish(page, report, Outcome.SKIPPED, "Already correct; no formula write was submitted.", details)

        details.update(stage="Clear old formula", expected_state="Empty formula editor")
        await _check_editor_focus(page, dialog, details)
        await page.keyboard.press("Backspace")
        await _after_action(page, details, "Clear old formula")
        if (await _read_formula(page, dialog, timeout_ms, details)).strip():
            raise _CandidateError("The old formula is still present after clearing; replacement was not pasted.")
        details["remaining_steps"].remove("clear old formula")
        _observe(page, details, "Formula editor is empty; no save submitted")
        details.update(stage="Paste new formula", expected_state="The exact supplied formula in the editor")
        await _check_editor_focus(page, dialog, details)
        # Use the editor's paste path. Typing multiline text triggers Monaco's
        # auto-indentation and auto-closing instead of preserving literal text.
        await dialog.locator('[aria-label="Formula input"][data-mode-id="airtableFormulas"]').evaluate("""(node, text) => {
            const active = node.ownerDocument.activeElement;
            if (!node.contains(active)) throw new Error('Formula editor lost keyboard focus');
            const transfer = new DataTransfer();
            transfer.setData('text/plain', text);
            const event = new ClipboardEvent('paste', {bubbles: true, cancelable: true, clipboardData: transfer});
            active.dispatchEvent(event);
            if (!event.defaultPrevented) throw new Error('Formula editor did not handle the paste operation');
        }""", FORMULA)
        await _after_action(page, details, "Paste exact supplied formula")
        details["entered_formula"] = await _read_formula(page, dialog, timeout_ms, details)
        if details["entered_formula"] != FORMULA:
            raise _CandidateError("Formula read-back differs from the supplied formula; Save was not attempted.")
        details["remaining_steps"].remove("paste new formula")
        _observe(page, details, "Exact supplied formula read back before Save")
        await _guard_dialogs(page, details, editor=True)
        await _click_step(page, dialog.get_by_role("button", name="Save", exact=True),
                          "Save", timeout_ms, details, submission="save_attempted")
        details.update(stage="Verify dependency confirmation", expected_state="Recorded field dependency confirmation")
        confirmation = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name=_IMPACT))
        confirmation = await _one(page, confirmation, "field dependency confirmation", timeout_ms)
        _observe(page, details, _text(await confirmation.inner_text()))
        details["dependency_confirmation"] = details["last_observed_state"]
        details["remaining_steps"].remove("Save")
        await _guard_dialogs(page, details, editor=True, confirmation=True)
        await _click_step(page, confirmation.get_by_role("button", name="Confirm change", exact=True),
                          "Confirm change", timeout_ms, details, submission="confirmation_attempted")
        details.update(stage="Verify save completion", expected_state="Confirmation and field customization closed")
        await confirmation.wait_for(state="hidden", timeout=timeout_ms)
        await dialog.wait_for(state="hidden", timeout=timeout_ms)
        await _guard_dialogs(page, details)
        details["remaining_steps"].remove("Confirm change")
        _observe(page, details, "Confirmation and field editor closed; persistence not yet verified")

        # Reopen only for read-back. Never Save or Confirm from verification.
        details.update(stage="Reload saved field", expected_state="Exact formula persists after reload")
        await page.reload(wait_until="domcontentloaded", timeout=settings.navigation_timeout_ms)
        await _after_action(page, details, "Reload for saved-formula verification")
        dialog = await _open_editor(page, timeout_ms, details)
        after = await _read_formula(page, dialog, timeout_ms, details)
        details["after_formula"] = after
        if after != FORMULA:
            details.update(stage="Verify reloaded formula", expected_state="Exact supplied formula after reload")
            _observe(page, details, "Reloaded formula differs from the supplied formula; see after_formula")
            raise _CandidateError("Saved formula did not match after reload. No submission was repeated.")
        details["reload_verified"] = True
        details["verification"].append("Complete formula exactly matches the supplied text after reload")
        await _close_editor(page, dialog, timeout_ms, details)
        details["remaining_steps"].remove("verify reload persistence")
        _observe(page, details, "Exact saved formula verified after reload; verification editor closed without submission")
        return _finish(page, report, Outcome.SUCCESS,
                       "Formula saved and confirmed once; exact text verified after reload.", details)
    except Exception as exc:
        LOGGER.exception("Multiple target market CORE failed at %s", details["stage"])
        # Keep the actual error/dialog text, including formula validation errors.
        try:
            observed = await page.get_by_role("dialog").all_inner_texts()
            if observed:
                _observe(page, details, " | ".join(observed))
            dom = {
                "url": page.url,
                "stage": details["stage"],
                "headers": await _header(page).evaluate_all("nodes => nodes.map(node => node.outerHTML)"),
                "dialogs": await page.get_by_role("dialog").evaluate_all("nodes => nodes.map(node => node.outerHTML)"),
            }
            diagnostic = artifact_path(settings.logs_dir, "multiple_target_market_core DOM", ".json")
            diagnostic.write_text(json.dumps(dom, indent=2, ensure_ascii=False), encoding="utf-8")
            details["diagnostic_dom"] = str(diagnostic)
            LOGGER.info("Formula diagnostics: %s", diagnostic)
        except Exception:
            LOGGER.exception("Could not capture the final field/dialog state")
        message = f"Failed at {details['stage']}: expected {details['expected_state']}. {type(exc).__name__}: {exc}"
        if details["reload_verified"]:
            message += " Formula persistence was verified, but closing the verification editor did not complete. No submission was repeated."
        elif details["save_attempted"] or details["confirmation_attempted"]:
            message += " A submission was attempted; the final saved formula remains unverified. It was not retried."
        return _finish(page, report, Outcome.FAILED, message, details)
