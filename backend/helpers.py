"""Shared semantic controls, interface navigation, and section validation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import re
import time

from playwright.async_api import Error as PlaywrightError, Locator, Page

from Backend.airtable_actions import (
    ActionReport,
    CandidateResult,
    Outcome,
    _CandidateError,
)


# 1. Workflow constants.
_ASSIGNMENT_AUTOMATION = (
    "[Media Plan] Button | Activator Assigned to Campaign Notification"
)
_RESET_AUTOMATION = "Change Activator – Reset Campaign Status"
_RESET_AUTOMATION_TEXT = re.compile(
    r"Change Activator.*Reset Campaign Status"
)
_SECTION_RETRIES = 1

# 2. Semantic controls and state checks.
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
