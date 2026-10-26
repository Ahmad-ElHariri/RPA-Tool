"""Exactly-once master publication and selected-installation push verification."""


# Workflow contract preserved from the former repository-wide instructions.
# - Attempt interface Publish, the recorded changed section, Select all, and final
#   Publish once. Do not replay publication, retry Select all, test whether the
#   header Publish is still clickable, or infer behavior from header change text.
# - Interface errors, including failed interface-section validation, are warnings.
#   Continue to the library and push. Dismiss only the identified interface Publish
#   dialog with its recorded Cancel control when needed.
# - Library publication and push success produce **Success with warnings** when
#   interface issues occurred. List affected apps and downstream outcomes in the
#   report's **Interface publish warnings** sheet. Do not hide those warnings or
#   let them alone fail the app or run.
# - Keep configured initial URL navigation and allow three minutes for initial
#   Airtable top-bar readiness. Remaining steps before the installation-list
#   **Push updates** click use fifteen-minute browser and navigation timeouts.
#   After that click,
#   confirmation, scrolling, and completion verification have no elapsed-time
#   deadlines. Do not add a push-completion cutoff or automatically repeat a push.
# - Preserve Airtable's selection. Read counts and states dynamically, with no
#   fixed number of installations or requirement for unique display names.
#   The library preview need not repeat the base-settings name.
# - Wheel events need not change virtualized row indices. Scrolling may pause
#   while updating. Nonselected bases do not have to become up to date.
# - Verify each target using the observed **Up to date** status. Closing a dialog
#   or losing **Updates available** does not prove completion. Preserve useful
#   error details and never resubmit a partial push automatically.

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable
import logging
import re
import time

from playwright.async_api import Error as PlaywrightError, Locator, Page

from Backend.helpers import (
    ActionReport,
    CandidateResult,
    Outcome,
    _CandidateError,
    _new_report,
)
from Backend.config import Settings
from Backend.helpers import _run_validated_section, _text, _visible


# 1. Workflow constants.
_PUSH_LOGGER = logging.getLogger(__name__)
_MASTER_TOPBAR_TIMEOUT_MS = 180_000
_MASTER_STEP_TIMEOUT_MS = 900_000

# 2. Semantic controls and state checks.
async def _master_wait(
    page: Page,
    predicate: Callable[[], Awaitable[bool]],
    description: str, timeout_ms: int,
) -> None:
    started = time.monotonic()
    next_log = started
    while True:
        try:
            if await predicate():
                _PUSH_LOGGER.info("%s completed after %.2f minutes", description,
                                 (time.monotonic() - started) / 60)
                return
        except PlaywrightError:
            if page.is_closed():
                raise
        elapsed = time.monotonic() - started
        if timeout_ms and elapsed >= timeout_ms / 1000:
            raise _CandidateError(f"Timed out waiting for {description} after {timeout_ms} ms.")
        if time.monotonic() >= next_log:
            _PUSH_LOGGER.info("Waiting for %s: %.2f minutes", description, elapsed / 60)
            next_log = time.monotonic() + 30
        await page.wait_for_timeout(1000)


async def _master_ready(page: Page, locator: Locator, description: str, timeout_ms: int) -> None:
    async def ready() -> bool:
        count = await locator.count()
        if count > 1:
            raise _CandidateError(f"Ambiguous {description}: {count} candidates.")
        return (count == 1 and await locator.is_visible()
                and await locator.is_enabled()
                and await locator.get_attribute("aria-busy") != "true")

    await _master_wait(page, ready, description, timeout_ms)


async def _master_click(page: Page, locator: Locator, description: str, timeout_ms: int) -> None:
    count = await locator.count()
    if count != 1:
        raise _CandidateError(f"Expected one {description}; found {count}.")
    if not await locator.is_visible() or not await locator.is_enabled():
        raise _CandidateError(f"{description} is unavailable.")
    await locator.click(timeout=timeout_ms)


async def _open_master_publish_section(
    page: Page, timeout_ms: int,
) -> tuple[Locator, Locator]:
    header = page.get_by_test_id("page-creator-chrome-header")
    await _master_click(page, header.get_by_role("button", name="Publish", exact=True),
                        "interface Publish", timeout_ms)
    dialog = page.get_by_role("dialog", name="Publish interfaces", exact=True)
    await _master_ready(page, dialog, "Publish interfaces dialog", timeout_ms)
    await _master_ready(page, dialog.get_by_role("button", name="Cancel", exact=True),
                        "loaded Publish interfaces dialog controls", timeout_ms)
    heading = dialog.get_by_text("Interfaces that have unpublished changes", exact=True)
    await _master_click(page, heading, "changed-interfaces section heading", timeout_ms)
    # 17. Airtable may insert an explanatory banner before the checkbox container.
    # Bound the siblings by the later section headings instead of adjacency.
    section = dialog.locator(
        'div:text-is("Interfaces that have unpublished changes") ~ div'
        ':not(div:text-is("Interfaces that are currently unpublished") ~ div)'
        ':not(div:text-is("Interfaces that have no changes") ~ div)'
    ).filter(
        has=page.get_by_role("group")
    )
    await _master_ready(page, section, "changed-interfaces section", timeout_ms)
    return dialog, section


async def _click_master_select_all(
    page: Page, dialog: Locator, section: Locator, names: tuple[str, ...], timeout_ms: int,
) -> int:
    await _master_click(page, section.get_by_role("button", name="Select all", exact=True),
                        "Select all changed interfaces", timeout_ms)

    async def all_selected() -> bool:
        if not await _visible(dialog) or not await _visible(section):
            raise _CandidateError("Interface publication dialog or section disappeared before selection was verified.")
        boxes = section.get_by_role("checkbox")
        current = tuple(_text(name) for name in await boxes.all_inner_texts())
        if sorted(current) != sorted(names):
            raise _CandidateError("Changed-interface list changed after Select all.")
        return await boxes.evaluate_all("boxes => boxes.every(b => b.getAttribute('aria-checked') === 'true')")

    await _master_wait(page, all_selected, "all changed interfaces selected", timeout_ms)
    return 1


async def _publish_master_interfaces(
    page: Page, report: ActionReport, timeout_ms: int,
) -> None:
    header = page.get_by_test_id("page-creator-chrome-header")
    await _master_ready(page, header, "Interface Designer header", timeout_ms)
    await _master_ready(page, page.get_by_test_id("page-creator-sidebar"),
                        "loaded Interface Designer settings sidebar", timeout_ms)

    label = "Interface publication"

    dialog, section = await _open_master_publish_section(page, timeout_ms)
    boxes = section.get_by_role("checkbox")
    names = tuple(_text(name) for name in await boxes.all_inner_texts())
    if not names:
        raise _CandidateError("The changed-interfaces section contains no checkboxes.")
    counts = Counter(names)
    items = {(name if name and counts[name] == 1 else f"{name or 'Interface'} (interface {number})"): name
             for number, name in enumerate(names, 1)}

    async def selected(item: str) -> bool:
        states = await boxes.evaluate_all("""boxes => boxes.map(b => ({
            name: b.innerText.replace(/\\s+/g, ' ').trim(),
            checked: b.getAttribute('aria-checked') === 'true'
        }))""")
        matching = [state for state in states if state["name"] == items[item]]
        return len(matching) == counts[items[item]] and all(state["checked"] for state in matching)

    changed = {item: not await selected(item) for item in items}
    selection_applied = False
    selection_verified = False

    async def apply(name: str) -> bool:
        nonlocal selection_applied, selection_verified
        if not selection_applied:
            selection_applied = True
            attempts = await _click_master_select_all(page, dialog, section, names, timeout_ms)
            selection_verified = True
            report.results.append(CandidateResult(
                candidate=label + ": Select all",
                outcome=Outcome.SUCCESS,
                message="Clicked Select all in Interfaces that have unpublished changes.",
                details={"interfaces": list(names), "attempts": attempts},
            ))
        return changed[name]

    async def validate_selection(name: str) -> bool:
        return selection_verified and await selected(name)

    if not await _run_validated_section(page, report, label, tuple(items),
                                        apply, validate_selection, timeout_ms, retries=0):
        raise _CandidateError("Changed-interface selection did not validate.")
    final_names = tuple(_text(name) for name in await boxes.all_inner_texts())
    if Counter(final_names) != counts:
        raise _CandidateError("Changed-interface list changed before Publish; refusing an incomplete selection.")
    for item in items:
        if not await selected(item):
            raise _CandidateError(f"Interface {item!r} is not selected before Publish.")
    await _master_click(page, dialog.get_by_role("button", name="Publish", exact=True),
                        "publish selected interfaces", timeout_ms)

    async def finished() -> bool:
        return not await _visible(dialog)

    await _master_wait(page, finished, label + " completion", timeout_ms)
    report.results.append(CandidateResult(
        candidate=label,
        outcome=Outcome.SUCCESS,
        message="Selected all changed interfaces and completed publication.",
        details={"interfaces": list(names)},
    ))


async def _master_table_state(table: Locator) -> dict:
    return await table.evaluate(r"""table => {
        const clean = el => {
            const copy = el.cloneNode(true);
            copy.querySelectorAll('[aria-hidden="true"]').forEach(n => n.remove());
            return copy.textContent.replace(/\s+/g, ' ').trim();
        };
        const columns = [...table.querySelectorAll('[role="columnheader"]')];
        const column = name => {
            const header = columns.find(c => c.getAttribute('data-column-id') === name);
            if (!header) throw new Error('Missing installation column: ' + name);
            return [...header.closest('[role="row"]').querySelectorAll(
                '[role="cell"], [role="columnheader"]')].indexOf(header);
        };
        const baseColumn = column('Base'), statusColumn = column('Status');
        const nodes = [...table.querySelectorAll('[role="row"][aria-rowindex]')];
        const rows = nodes.map(row => {
            const cells = row.querySelectorAll('[role="cell"]');
            const boxes = row.querySelectorAll('input[type="checkbox"], [role="checkbox"]');
            if (boxes.length !== 1) throw new Error('Ambiguous installation checkbox');
            const link = cells[baseColumn].querySelector('a[href]');
            const name = clean(cells[baseColumn]);
            const href = link ? link.getAttribute('href').split('?')[0] : '';
            return {index: row.getAttribute('aria-rowindex'), name, href,
                key: href || name, selected: boxes[0].checked ??
                    boxes[0].getAttribute('aria-checked') === 'true',
                status: clean(cells[statusColumn])};
        });
        const scrollers = new Set();
        for (const row of nodes) {
            for (let parent = row.parentElement; parent && parent !== table;
                 parent = parent.parentElement) {
                if (parent.scrollHeight > parent.clientHeight &&
                    /auto|scroll|overlay/.test(getComputedStyle(parent).overflowY)) {
                    scrollers.add(parent); break;
                }
            }
        }
        if (scrollers.size > 1) throw new Error('Ambiguous installation scroll region');
        const [scroll] = scrollers;
        const description = (table.getAttribute('aria-describedby') || '').split(/\s+/)
            .map(id => document.getElementById(id)?.textContent || '').join(' ');
        const total = description.match(/This table contains (\d+) rows?\./);
        return {rows, total: total ? Number(total[1]) : null,
            top: scroll?.scrollTop || 0, height: scroll?.clientHeight || 0,
            bottom: !scroll || scroll.scrollTop + scroll.clientHeight >= scroll.scrollHeight - 1};
    }""")


async def _master_installation_rows(
    page: Page, table: Locator, timeout_ms: int,
) -> list[dict]:
    scroller = table.get_by_test_id("basic-table-contents").get_by_role("rowgroup").locator("..")
    rows: dict[str, dict] = {}
    total = None

    async def collect() -> bool:
        nonlocal total
        state = await _master_table_state(table)
        if state["total"] is None:
            return False
        if state["total"] != total:
            total = state["total"]
            rows.clear()
        rows.update((row["index"], row) for row in state["rows"])
        if len(rows) == total:
            return True
        delta = -state["top"] if state["bottom"] else state["height"]
        if delta:
            await scroller.hover(timeout=timeout_ms)
            await page.mouse.wheel(0, delta)
        return False

    # 18. A wheel event need not change virtualized row indices, and Airtable may
    # temporarily freeze scrolling during a push; only post-click waits are unlimited.
    await _master_wait(page, collect, "all installation rows", timeout_ms)
    return list(rows.values())


async def _master_installations(
    page: Page, library: Locator, timeout_ms: int,
) -> tuple[Locator, list[dict]]:
    table = library.get_by_role("table")
    push = library.get_by_role("button", name="Push updates", exact=True)
    await _master_ready(page, push, "loaded installation selection", timeout_ms)
    await _master_ready(page, table, "installed-base table", timeout_ms)
    selection = table.get_by_text(re.compile(r"^\d+ selected$"))
    footer = library.get_by_text(re.compile(r"^\d+ bases? will be updated\.$"))
    await _master_ready(page, selection, "installation selection count", timeout_ms)
    await _master_ready(page, footer, "installation push count", timeout_ms)
    count = int((await selection.inner_text()).split()[0])
    rows = await _master_installation_rows(page, table, timeout_ms)
    selected = [row for row in rows if row["selected"]]
    if len(selected) != count or int((await footer.inner_text()).split()[0]) != count:
        raise _CandidateError("Selected installations do not match Airtable's push count.")
    return table, selected


async def _publish_master_library(
    page: Page, topbar: Locator, phase: CandidateResult, timeout_ms: int,
) -> tuple[Locator, Locator]:
    library_button = topbar.get_by_role("button", name="Publish to library", exact=True)
    await _master_ready(page, library_button, "Publish to library", timeout_ms)
    await _master_click(page, library_button, "Publish to library", timeout_ms)
    library = page.get_by_role("dialog", name="Packages library generic modal", exact=True)
    update = library.filter(has=page.get_by_role("heading", name="Publish an update", exact=True))
    publish = update.get_by_role("button", name="Publish", exact=True)
    await _master_ready(page, publish, "library update preview", timeout_ms)
    await _master_click(page, publish, "publish library update", timeout_ms)
    confirmation = page.get_by_role("dialog", name="Are you sure you want to publish this update?", exact=True)
    confirm_publish = confirmation.get_by_role("button", name="Publish", exact=True)
    published_heading = page.get_by_role("heading", name=re.compile(r".+ has been published$"))
    success = library.filter(has=published_heading)
    push = success.get_by_role("button", name="Push update", exact=True)

    async def confirmation_or_success() -> bool:
        return await _visible(confirmation) or await _visible(success)

    await _master_wait(page, confirmation_or_success,
                       "library publication confirmation or success", timeout_ms)
    if await _visible(success):
        _PUSH_LOGGER.info("Library publication success is already visible; continuing to Push update.")
    else:
        await _master_ready(page, confirm_publish, "library publication confirmation", timeout_ms)
        await _master_click(page, confirm_publish, "confirm library publication", timeout_ms)
    await _master_ready(page, push, "master app publication success", timeout_ms)
    phase.outcome = Outcome.SUCCESS
    phase.message = _text(await success.get_by_role("heading", name=re.compile(r".+ has been published$")).inner_text())
    return library, push


async def _push_master_library(
    page: Page, library: Locator, push: Locator, phase: CandidateResult, report: ActionReport, timeout_ms: int,
) -> None:
    await _master_click(page, push, "Push update", timeout_ms)
    _PUSH_LOGGER.info("Clicked Push update; waiting for the installation list at %s.", page.url)
    table, installations = await _master_installations(page, library, timeout_ms)
    phase.details["installed_bases"] = installations
    # 20. Duplicate display names are valid for a batch; verify the whole group.
    expected = Counter(row["key"] for row in installations)
    completed: Counter = Counter()
    attempted = False
    confirm_push = page.get_by_test_id("package-push-update-confirm-button")
    confirm = page.get_by_role("dialog").filter(has=confirm_push)

    async def pushed() -> bool:
        nonlocal completed
        if await _visible(confirm) or not await _visible(table):
            return False
        rows = await _master_installation_rows(page, table, 0)
        completed = Counter()
        for key, count in expected.items():
            group = [row for row in rows if row["key"] == key]
            selected = [row for row in group if row["selected"]]
            targets = group if len(group) == count else selected
            if len(targets) == count and all(row["status"] == "Up to date" for row in targets):
                completed[key] = count
        return completed == expected

    async def apply_push(item: str) -> bool:
        nonlocal attempted
        if not attempted:
            attempted = True
            await _master_click(page, library.get_by_role("button", name="Push updates", exact=True),
                                "Push updates to the selected installations", timeout_ms)
            # 21. Only the work after Push updates has no elapsed-time deadline.
            page.set_default_timeout(0)
            page.set_default_navigation_timeout(0)
            await _master_ready(page, confirm_push, "installed-base push confirmation", 0)
            await _master_click(page, confirm_push, "Confirm push", 0)
            phase.details["submitted"] = True
            try:
                await _master_wait(page, pushed, "selected installations Up to date", 0)
            except (_CandidateError, PlaywrightError) as exc:
                phase.details["verification_error"] = str(exc)
                raise
        return True

    items = {f"{row['name']} (installation {number})": row["key"]
             for number, row in enumerate(installations, 1)}

    async def validate_push(item: str) -> bool:
        return bool(phase.details.get("submitted")) and completed[items[item]] == expected[items[item]]

    if not await _run_validated_section(
        page, report, "Installed base push", tuple(items), apply_push, validate_push,
        0, retries=0,
    ):
        raise _CandidateError("Push did not verify every selected installation; no submission was repeated.")
    phase.outcome = Outcome.SUCCESS
    phase.message = f"Push completed; all {len(installations)} selected installations are Up to date."

# 3. Workflow entry point.
async def push_master_apps(page: Page, settings: Settings) -> ActionReport:
    """Attempt interface publication once, then continue to the library and push."""
    action_name = 'push_master_apps'
    report = _new_report(action_name, page)
    timeout_ms = _MASTER_STEP_TIMEOUT_MS
    page.set_default_timeout(timeout_ms)
    page.set_default_navigation_timeout(timeout_ms)
    phases = [CandidateResult(name, Outcome.FAILED, "Not processed or verified.")
              for name in ("Changed interfaces", "Master app library publication", "Installed base push")]
    phases[0].outcome = Outcome.WARNING
    report.results.extend(phases)
    phase = phases[0]
    started = time.monotonic()
    try:
        # 19. Existing dialogs could represent a previous submission; never infer recovery.
        if await page.locator('[role="dialog"]:visible').count():
            raise _CandidateError("An existing dialog makes the starting state ambiguous.")
        topbar = page.get_by_test_id("appTopbar")
        await _master_ready(page, topbar, "Airtable top bar", _MASTER_TOPBAR_TIMEOUT_MS)
        interface_results_start = len(report.results)
        try:
            await _master_click(page, topbar.get_by_role("link", name="Interfaces", exact=True),
                                "Interfaces navigation", timeout_ms)
            await _publish_master_interfaces(page, report, timeout_ms)
            phase.outcome = Outcome.SUCCESS
            phase.message = "Selected all changed interfaces and clicked Publish once."
        except Exception as exc:
            phase.outcome = Outcome.WARNING
            phase.message = f"INTERFACE PUBLICATION WARNING; continuing to library and push: {exc}"
            for result in report.results[interface_results_start:]:
                if result.outcome == Outcome.FAILED:
                    result.outcome = Outcome.WARNING
            phase.details.update({
                "interface_publication_warning": True,
                "interface_error": f"{type(exc).__name__}: {exc}",
                "stage_url": page.url,
            })
            _PUSH_LOGGER.warning("Interface publication warning at %s; continuing to library: %s",
                                 page.url, exc)
            dialog = page.get_by_role("dialog", name="Publish interfaces", exact=True)
            try:
                if await _visible(dialog):
                    await _master_click(page, dialog.get_by_role("button", name="Cancel", exact=True),
                                        "dismiss incomplete interface publication", timeout_ms)

                    async def dismissed() -> bool:
                        return not await _visible(dialog)

                    await _master_wait(page, dismissed, "interface publication dialog to close", timeout_ms)
            except (_CandidateError, PlaywrightError) as cleanup_error:
                phase.details["dialog_cleanup_error"] = str(cleanup_error)

        phase = phases[1]
        library, push = await _publish_master_library(page, topbar, phase, timeout_ms)
        phase = phases[2]
        await _push_master_library(page, library, push, phase, report, timeout_ms)
    except (_CandidateError, PlaywrightError) as exc:
        phase.message = str(exc)
        phase.details["stage_url"] = page.url
    finally:
        page.set_default_timeout(settings.browser_timeout_ms)
        page.set_default_navigation_timeout(settings.navigation_timeout_ms)
        phase.details["elapsed_minutes"] = round((time.monotonic() - started) / 60, 2)
    return report.finish(page)

