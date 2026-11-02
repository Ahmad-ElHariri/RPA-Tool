"""Add Campaign Status is Live to the three recorded pacing-alert branches.

Evidence: Nestle__page__recording  -  11-02__10.56.json, all 28 clicks.
Preserve the two original AND conditions and all existing actions. Exact
three-condition branches may be skipped by user agreement. Preflight all
branches before writing; stop on other states or existing unpublished changes.
Actions wait three seconds; final Update is attempted once and waits six.
Verify all three conditions in every branch again after applying and reloading.
No automatic edit recovery or submission retries.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import Locator, Page

from Backend.config import Settings, artifact_path, lebanon_now
from Backend.helpers import (
    ActionReport, CandidateResult, Outcome, _CandidateError, _new_report, _one,
    _run_validated_section, _text, _wait_until,
)


LOGGER = logging.getLogger(__name__)
_AUTOMATION = "Alert Activation and Planning if Spend diff. 25%-50%-80%"
_DIFFERENCE = "Duration vs. Budget Completion % Diff."
_BLOCKS = {"25%": ("-0.25", ""), "50%": ("-0.5", "25%"), "80%": ("-0.8", "50%")}
_ACTION_WAIT_MS = 3_000
_UPDATE_WAIT_MS = 6_000
_UNPUBLISHED = re.compile(r"^You have unpublished changes")


# 1. Keep live locators, action evidence and explicit timing together.
def _observe(page: Page, details: dict, state: str) -> None:
    details.update(last_observed_state=state, last_observed_url=page.url,
                   last_observed_at=lebanon_now().isoformat())


async def _wait_after(page: Page, details: dict, step: str, milliseconds: int = _ACTION_WAIT_MS) -> None:
    action = {"step": step, "wait_seconds": milliseconds / 1000, "wait_completed": False}
    details["actions"].append(action)
    LOGGER.info("%s; waiting %g seconds", step, action["wait_seconds"])
    await page.wait_for_timeout(milliseconds)
    action["wait_completed"] = True


async def _click(page: Page, target: Locator, step: str, settings: Settings, details: dict,
                 *, update: bool = False) -> None:
    details.update(stage=step, expected_state=f"One visible, enabled {step} control")
    target = await _one(page, target, step, settings.browser_timeout_ms)
    if await target.get_attribute("aria-disabled") == "true" or await target.get_attribute("aria-busy") == "true":
        raise _CandidateError(f"{step} is disabled or busy; no click attempted.")
    if update:
        if details["update_attempted"]:
            raise _CandidateError("Update was already attempted; it will not be repeated.")
        details["update_attempted"] = True
    await target.click(timeout=settings.browser_timeout_ms)
    await _wait_after(page, details, step, _UPDATE_WAIT_MS if update else _ACTION_WAIT_MS)


def _group(page: Page, block: str) -> Locator:
    threshold, _ = _BLOCKS[block]
    return page.get_by_test_id("workflows-canvas").get_by_role("group").filter(
        has_text=re.compile(rf"^(?:Otherwise if|If) {re.escape(_DIFFERENCE)}\s*<\s*{re.escape(threshold)}(?:\s|,|$)"))


def _header(text: str) -> str:
    return re.sub(r"\s+,", ",", _text(text.split("Send an email and Update a record", 1)[0]))


def _expected_header(block: str, complete: bool) -> str:
    threshold, pacing = _BLOCKS[block]
    prefix = "If" if block == "25%" else "Otherwise if"
    first = f"{prefix} {_DIFFERENCE} <{threshold}"
    second = "Pacing Alerts is " + (pacing or "empty")
    return f"{first}, {second}, and Campaign Status is Live" if complete else f"{first} and {second}"


async def _draft_status(page: Page, details: dict) -> bool:
    banners = await page.get_by_text(_UNPUBLISHED).all_inner_texts()
    saved = page.get_by_text("All changes saved", exact=True)
    save_observed = await saved.count() == 1 and await saved.is_visible()
    details["last_observed_airtable_status"] = " | ".join([
        "All changes saved" if save_observed else "Separate save/status indicator unobserved",
        " | ".join(map(_text, banners)) if banners else "Unpublished-changes banner absent"])
    return bool(banners)


async def _open_editor(page: Page, block: str, settings: Settings, details: dict) -> Locator:
    details.update(stage=f"Select {block} block", expected_state=f"The unique {block} pacing branch")
    group = await _one(page, _group(page, block), f"{block} block", settings.browser_timeout_ms)
    await _click(page, group.get_by_text("Send an email and Update a record", exact=True),
                 f"Select {block} block", settings, details)
    # The recorded branch selection changes the URL index, unlike action-card focus.
    async def selected() -> bool:
        return parse_qs(urlsplit(page.url).query).get("index") == [str(tuple(_BLOCKS).index(block))]
    await _wait_until(page, selected, f"{block} branch selection", settings.browser_timeout_ms)
    await _click(page, page.get_by_role("button", name="Edit conditions", exact=True),
                 f"Edit {block} conditions", settings, details)
    return await _one(page, page.get_by_test_id("conditional-editor-modal"),
                      "conditional editor", settings.browser_timeout_ms)


def _rows(editor: Locator) -> Locator:
    # Remove condition belongs to each row. Its nearest ancestor containing an
    # operator is the entire row, including the field, connector and comparison.
    return editor.get_by_role("button", name="Remove condition", exact=True).locator(
        'xpath=ancestor::div[.//*[@data-testid="autocomplete-button"]][1]')


async def _read_rows(editor: Locator) -> list[dict]:
    return await _rows(editor).evaluate_all("""nodes => nodes.map(row => {
        const norm = text => (text || '').replace(/\\s+/g, ' ').trim();
        const source = row.querySelectorAll('[aria-description="Tooltip: SOURCE:When a record is updated"]');
        const fields = Array.from(source).flatMap(node => Array.from(node.querySelectorAll('[title]')).map(n => n.title));
        return {
            fields,
            sources: Array.from(source).map(n => n.getAttribute('aria-description')),
            operators: Array.from(row.querySelectorAll('[data-testid="autocomplete-button"][role="button"]')).map(n => norm(n.innerText)),
            inputs: Array.from(row.querySelectorAll('input[aria-label="Condition comparison value"]')).map(n => n.value),
            choices: Array.from(row.querySelectorAll('[role="combobox"]')).map(n => {
                const label = n.getAttribute('aria-label'), value = norm(n.innerText);
                // Airtable appends the selected value to the accessible label.
                const field = fields.length === 1 && label === fields[0] + ', ' + value ? fields[0] : label;
                return {field, value};
            }),
            connectors: Array.from(row.querySelectorAll('[role="button"], [data-testid="filter-prefix-label"]')).map(n => norm(n.innerText)).filter(t => t === 'and' || t === 'or'),
        };
    })""")


def _expected_rows(block: str, complete: bool) -> list[dict]:
    threshold, pacing = _BLOCKS[block]
    def row(field, operator, *, inputs=None, choices=None, connector=False):
        return {"fields": [field], "sources": ["Tooltip: SOURCE:When a record is updated"],
                "operators": [operator], "inputs": inputs or [], "choices": choices or [],
                "connectors": ["and"] if connector else []}
    result = [row(_DIFFERENCE, "<", inputs=[threshold]),
              row("Pacing Alerts", "is" if pacing else "is empty", connector=True,
                  choices=[{"field": "Pacing Alerts", "value": pacing}] if pacing else [])]
    if complete:
        result.append(row("Campaign Status", "is", connector=True,
                          choices=[{"field": "Campaign Status", "value": "Live"}]))
    return result


async def _close_editor(page: Page, editor: Locator, settings: Settings, details: dict) -> None:
    # The recording dismisses the popover by clicking the canvas, with no submission.
    await _click(page, page.get_by_test_id("workflows-canvas"), "Close condition editor on canvas", settings, details)
    await editor.wait_for(state="hidden", timeout=settings.browser_timeout_ms)


# 2. Preflight every branch before making any draft changes.
async def _preflight(page: Page, settings: Settings, details: dict) -> None:
    if await _draft_status(page, details):
        raise _CandidateError("Existing unpublished changes found; applying them is outside this workflow.")
    canvas = await _one(page, page.get_by_test_id("workflows-canvas"), "workflow canvas", settings.browser_timeout_ms)
    if await canvas.get_by_role("group").count() != 3:
        raise _CandidateError("Expected exactly three conditional blocks in the automation.")
    for block in _BLOCKS:
        editor = await _open_editor(page, block, settings, details)
        details.update(stage=f"Validate {block} original conditions", expected_state="Recorded original two or exact required three AND conditions")
        rows = await _read_rows(editor)
        details["blocks"][block]["before"] = rows
        _observe(page, details, f"{block} before: {json.dumps(rows, ensure_ascii=False)}")
        if rows not in (_expected_rows(block, False), _expected_rows(block, True)):
            raise _CandidateError(f"{block} conditions differ from the recorded original two or exact required three; no edits attempted.")
        header = _header(await _group(page, block).inner_text())
        if header != _expected_header(block, len(rows) == 3):
            raise _CandidateError(f"{block} summary disagrees with its condition rows: {header!r}.")
        await _close_editor(page, editor, settings, details)
    if await _draft_status(page, details):
        raise _CandidateError("Unpublished changes appeared during read-only preflight; no edits attempted.")


async def _add_condition(page: Page, block: str, settings: Settings, details: dict) -> bool:
    item = details["blocks"][block]
    editor = await _open_editor(page, block, settings, details)
    current = await _read_rows(editor)
    if current != item["before"]:
        raise _CandidateError(f"{block} changed since preflight; refusing to edit it.")
    if current == _expected_rows(block, True):
        item["skip_reason"] = "Exact three required AND conditions already present; left unchanged by user agreement"
        await _close_editor(page, editor, settings, details)
        return False
    item["edit_attempted"] = True
    await _click(page, editor.get_by_role("button", name="Add condition", exact=True),
                 f"Add {block} condition", settings, details)
    if await _rows(editor).count() != 3 or (await _read_rows(editor))[:2] != current:
        raise _CandidateError(f"{block}: adding a condition did not preserve the original two rows.")
    # Only the blank new row has Use dynamic data and no source field token.
    blank = _rows(editor).filter(has=page.get_by_role("button", name="Use dynamic data", exact=True))
    await _click(page, blank.get_by_role("button", name="Use dynamic data", exact=True),
                 f"Choose {block} dynamic field", settings, details)
    builder = await _one(page, page.get_by_test_id("expression-builder-container"),
                         "dynamic field picker", settings.browser_timeout_ms)
    field = builder.get_by_text("Campaign Status", exact=True).locator('xpath=ancestor::*[@role="button"][1]')
    await _click(page, field, f"Choose {block} Campaign Status", settings, details)
    await builder.wait_for(state="hidden", timeout=settings.browser_timeout_ms)
    choice = await _one(page, editor.get_by_role("combobox", name="Campaign Status", exact=True),
                        "Campaign Status choice", settings.browser_timeout_ms)
    await _click(page, choice, f"Open {block} Campaign Status options", settings, details)
    options = await _one(page, page.get_by_role("listbox"), "Campaign Status options", settings.browser_timeout_ms)
    await _click(page, options.get_by_role("option", name="Live", exact=True),
                 f"Choose {block} Live", settings, details)
    await options.wait_for(state="hidden", timeout=settings.browser_timeout_ms)
    details.update(stage=f"Validate {block} draft conditions", expected_state="Original two AND conditions plus Campaign Status is Live")
    item["draft_after"] = await _read_rows(editor)
    _observe(page, details, f"{block} draft: {json.dumps(item['draft_after'], ensure_ascii=False)}")
    if item["draft_after"] != _expected_rows(block, True):
        raise _CandidateError(f"{block} does not have the exact three required AND conditions; Update will not be attempted.")
    await _close_editor(page, editor, settings, details)
    item["changed"] = True
    return True


# 3. Apply once, then verify the entire section from the reloaded editor.
async def _publish(page: Page, settings: Settings, details: dict) -> None:
    details.update(stage="Validate all draft blocks before Update", expected_state="Three complete, preserved AND conditions in every block")
    for block in _BLOCKS:
        actual = _header(await _group(page, block).inner_text())
        if actual != _expected_header(block, True):
            raise _CandidateError(f"{block} draft summary is unexpected: {actual!r}; no Update attempted.")
    if any(item["changed"] for item in details["blocks"].values()):
        if not await _draft_status(page, details):
            raise _CandidateError("Draft edits were made but the expected unpublished-changes banner is absent.")
        await _click(page, page.get_by_role("button", name="Update", exact=True),
                     "Update automation", settings, details, update=True)
        details.update(stage="Verify Update applied", expected_state="Unpublished-changes banner and Update button gone")
        await page.get_by_text(_UNPUBLISHED).wait_for(state="hidden", timeout=settings.browser_timeout_ms)
        await page.get_by_role("button", name="Update", exact=True).wait_for(state="hidden", timeout=settings.browser_timeout_ms)
        details["update_applied"] = True
    elif await _draft_status(page, details):
        raise _CandidateError("Unexpected unpublished changes on an already-correct automation; no Update attempted.")
    await _draft_status(page, details)
    details.update(stage="Reload for condition verification", expected_state="Required three conditions persist in all blocks")
    await page.reload(wait_until="domcontentloaded", timeout=settings.navigation_timeout_ms)
    await _wait_after(page, details, "Reload for condition verification")
    await _one(page, page.get_by_test_id("workflows-canvas"), "reloaded automation canvas", settings.browser_timeout_ms)
    if await _draft_status(page, details):
        raise _CandidateError("Unpublished changes remain after reload; live update is unverified.")
    details["ready_to_verify"] = True


async def _verify_block(page: Page, block: str, settings: Settings, details: dict) -> bool:
    if not details["ready_to_verify"]:
        return False
    details.update(stage=f"Verify {block} after reload", expected_state=f"{block}: original two conditions and Campaign Status is Live, joined with AND")
    editor = await _open_editor(page, block, settings, details)
    details.update(stage=f"Verify {block} after reload", expected_state=f"{block}: original two conditions and Campaign Status is Live, joined with AND")
    rows = await _read_rows(editor)
    item = details["blocks"][block]
    item["after"] = rows
    item["verified"] = rows == _expected_rows(block, True) and rows[:2] == item["before"][:2]
    _observe(page, details, f"{block} after reload: {json.dumps(rows, ensure_ascii=False)}")
    await _close_editor(page, editor, settings, details)
    if item["verified"]:
        details["remaining_work"].remove(f"Verify {block} three conditions after reload")
    return item["verified"]


async def _diagnostics(page: Page, settings: Settings, details: dict) -> None:
    try:
        await _draft_status(page, details)
        data = {"url": page.url, "stage": details["stage"],
                "editors": await page.get_by_test_id("conditional-editor-modal").evaluate_all("nodes=>nodes.map(n=>n.outerHTML)"),
                "builders": await page.get_by_test_id("expression-builder-container").evaluate_all("nodes=>nodes.map(n=>n.outerHTML)"),
                "groups": await page.get_by_test_id("workflows-canvas").get_by_role("group").evaluate_all("nodes=>nodes.map(n=>n.outerHTML)"),
                "dialogs": await page.get_by_role("dialog").all_inner_texts()}
        path = artifact_path(settings.logs_dir, "alert_overspent failure DOM", ".json")
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        details["diagnostic_dom"] = str(path)
        observed = await page.get_by_test_id("conditional-editor-modal").all_inner_texts()
        observed += await page.get_by_test_id("workflows-canvas").get_by_role("group").all_inner_texts()
        _observe(page, details, " | ".join(data["dialogs"] + observed) or details["last_observed_state"])
        LOGGER.info("Alert overspent diagnostics: %s", path)
    except Exception:
        LOGGER.exception("Could not capture alert_overspent diagnostics")


async def alert_overspent(page: Page, settings: Settings) -> ActionReport:
    """Add and verify Campaign Status is Live in all three pacing branches."""
    report = _new_report("alert_overspent", page)
    details = {"stage": "Initial navigation", "expected_state": "Recorded pacing-alert automation",
               "actions": [], "blocks": {b: {"before": "Unobserved", "after": "Unobserved",
                                                "changed": False, "verified": False} for b in _BLOCKS},
               "update_attempted": False, "update_applied": False, "ready_to_verify": False,
               "last_observed_airtable_status": "Unobserved",
               "remaining_work": [f"Verify {b} three conditions after reload" for b in _BLOCKS]}
    _observe(page, details, "Target loaded; automation conditions not yet observed")
    try:
        await _wait_after(page, details, "Wait after initial target navigation")
        await _click(page, page.get_by_test_id("appTopbar").get_by_role("link", name="Automations", exact=True),
                     "Open Automations", settings, details)
        await _click(page, page.get_by_role("button", name=_AUTOMATION, exact=True),
                     "Open pacing-alert automation", settings, details)
        await _one(page, page.get_by_test_id("workflows-canvas"), "automation canvas", settings.browser_timeout_ms)
        await _preflight(page, settings, details)
        aborted = False

        async def apply(block: str) -> bool:
            nonlocal aborted
            if aborted:
                raise _CandidateError("An earlier block failed; this block was not edited.")
            try:
                return await _add_condition(page, block, settings, details)
            except Exception:
                aborted = True
                LOGGER.exception("Alert overspent failed while editing %s", block)
                raise

        async def publish(_: Page, __: int) -> None:
            try:
                await _publish(page, settings, details)
            except Exception:
                LOGGER.exception("Alert overspent failed at %s", details["stage"])
                raise

        async def verify(block: str) -> bool:
            try:
                return await _verify_block(page, block, settings, details)
            except Exception:
                LOGGER.exception("Alert overspent failed while verifying %s", block)
                raise

        await _run_validated_section(page, report, _AUTOMATION, tuple(_BLOCKS), apply, verify,
                                     settings.browser_timeout_ms, save_waiter=publish, retries=0)
    except Exception as exc:
        LOGGER.exception("Alert overspent failed at %s", details["stage"])
        report.results.append(CandidateResult(_AUTOMATION, Outcome.FAILED,
            f"Failed at {details['stage']}: expected {details['expected_state']}. {type(exc).__name__}: {exc}"))
    if not report.ok:
        await _diagnostics(page, settings, details)
    else:
        await _draft_status(page, details)
        _observe(page, details, "All three blocks verified after reload: original two AND conditions plus Campaign Status is Live")
        if not any(item["changed"] for item in details["blocks"].values()):
            for result in report.results:
                result.outcome = Outcome.SKIPPED
    for result in report.results:
        result.details.update(details)
    return report.finish(page)
