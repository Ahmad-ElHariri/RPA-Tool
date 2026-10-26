"""Workflow: smart_import_core. Task steps and private controls."""

from __future__ import annotations

import time
from playwright.async_api import ElementHandle, Error as PlaywrightError, Frame, Locator, Page
from Backend.config import Settings
from Backend.helpers import (
    ActionReport,
    CandidateResult,
    Outcome,
    _CandidateError,
    _new_report,
    _require_one,
    _run_core_validated_section,
)


_SMART_IMPORT_EXTRA_FIELDS = (
    ("CPC", "number"),
    ("CPM", "number"),
    ("CPA", "number"),
    ("CPV", "number"),
    ("CPE", "number"),
    ("CPI", "number"),
    ("CPCV", "number"),
    ("CPL", "number"),
    ("CPUR", "number"),
    ("CTR", "number"),
    ("VTR", "number"),
    ("Campaign Name Reference", "text"),
    ("Start Date", "date"),
    ("End Date", "date"),
    ("Objective (Core)", "text"),
    ("Audience", "text"),
    ("Creative Details", "text"),
    ("Budget Split Details", "text"),
    ("Budget", "number"),
)


_SMART_IMPORT_LINKED_TABLES = (
    "Brand",
    "Sub-Brand",
    "Markets",
    "Buying Model",
    "Platforms",
    "Language",
)


_SMART_IMPORT_INLINE_EDIT_TABLES = (
    "Field Mapping Sessions",
    "\N{LOCK} Sync Control",
    "Mapping",
    "Smart Import Field Mappings",
    *_SMART_IMPORT_LINKED_TABLES,
)


_SMART_IMPORT_INSTALLATION_TEST_ID = (
    "page-element:blockInstallationInQueryContainer"
)


_SMART_IMPORT_INSTALLATION_CLICKS = 1


async def _wait_for_smart_import_frame(page: Page, timeout_ms: int) -> Frame:
    """Find the extension iframe by origin and its visible product heading."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        for frame in page.frames:
            if "airtableblocks.com/__runFrame" not in frame.url:
                continue
            try:
                body = frame.locator("body")
                if await body.count() != 1:
                    continue
                normalized_text = " ".join((await body.inner_text()).split())
                if "Smart Import CORE" in normalized_text:
                    return frame
            except PlaywrightError:
                continue
        if time.monotonic() >= deadline:
            raise _CandidateError(
                "Could not find the loaded Smart Import CORE extension frame."
            )
        await page.wait_for_timeout(250)


def _smart_import_option_text_matches(
    text: str, field_name: str, field_type: str
) -> bool:
    # Tolerate the mojibake form found in some inspection output, but compare the
    # complete normalized row so fields such as CPC and CPCV cannot be confused.
    normalized = " ".join(text.replace("Â·", "·").split())
    return normalized == f"{field_name} · {field_type}"


async def _smart_import_field_is_configured(
    extra_fields_section: Locator, field_name: str, field_type: str
) -> bool:
    expected_text = f"{field_name} {field_type}"
    for text in await extra_fields_section.locator("*").all_inner_texts():
        if not text:
            continue
        normalized = " ".join(text.split())
        if normalized == expected_text or normalized.startswith(
            f"{expected_text} "
        ):
            return True
    return False


async def _click_smart_import_field(
    page: Page,
    frame: Frame,
    field_name: str,
    field_type: str,
    timeout_ms: int,
) -> bool:
    """Add one extra field, returning False when it is already configured."""
    extra_fields_section = frame.get_by_text(
        "Extra mappable fields", exact=True
    ).locator(
        "xpath=ancestor::*[.//input[@role='combobox']][1]"
    )
    if await _smart_import_field_is_configured(
        extra_fields_section, field_name, field_type
    ):
        return False

    combobox = await _require_one(
        page,
        extra_fields_section.get_by_role("combobox"),
        "Smart Import CORE 'Add a field' combobox",
        timeout_ms,
    )
    await combobox.click()
    await combobox.fill(field_name)
    option_locator = frame.locator('li[role="option"]')
    deadline = time.monotonic() + timeout_ms / 1000

    while True:
        candidates: list[ElementHandle] = []
        for handle in await option_locator.element_handles():
            try:
                text = await handle.inner_text()
                if (
                    _smart_import_option_text_matches(
                        text, field_name, field_type
                    )
                    and await handle.is_visible()
                    and await handle.is_enabled()
                ):
                    candidates.append(handle)
            except PlaywrightError:
                continue

        if len(candidates) == 1:
            await candidates[0].click()
            return True
        elif len(candidates) > 1:
            raise _CandidateError(
                f"Found {len(candidates)} usable options for Smart Import CORE "
                f"field {field_name!r} ({field_type}); refusing to choose by position."
            )

        if time.monotonic() >= deadline:
            action = "find"
            raise _CandidateError(
                f"Could not {action} Smart Import CORE field "
                f"{field_name!r} ({field_type})."
            )
        await page.wait_for_timeout(250)


async def _page_table_is_added(table: ElementHandle) -> bool | None:
    """Read Airtable's Show/Hide action without toggling the table."""
    try:
        action_description = await table.eval_on_selector(
            "[aria-description]",
            "element => element.getAttribute('aria-description')",
        )
    except PlaywrightError:
        return None
    if not isinstance(action_description, str):
        return None
    normalized = action_description.casefold()
    if "hide" in normalized:
        return True
    if "show" in normalized:
        return False
    return None


async def _smart_import_table(
    page: Page, table_name: str, timeout_ms: int
) -> ElementHandle:
    """Find a table in the popover, opening it when necessary."""
    dialog = page.get_by_test_id("popover:Table")
    dialog_is_open = False
    for handle in await dialog.element_handles():
        try:
            if await handle.is_visible():
                dialog_is_open = True
                break
        except PlaywrightError:
            continue

    if not dialog_is_open:
        sidebar = page.get_by_test_id("page-creator-sidebar")
        open_popover = await _require_one(
            page,
            sidebar.get_by_role(
                "button", name="open Table popover", exact=True
            ),
            "Interface Designer open Table popover button",
            timeout_ms,
        )
        await open_popover.click()

    search = await _require_one(
        page,
        dialog.get_by_role("textbox"),
        "Table popover search input",
        timeout_ms,
    )
    await search.fill(table_name)
    table = await _require_one(
        page,
        dialog.get_by_role("listitem"),
        f"Table dialog item {table_name!r}",
        timeout_ms,
        exact_text=table_name,
    )
    return table


async def _ensure_smart_import_table(
    page: Page, table_name: str, timeout_ms: int
) -> bool:
    """Apply one table change; final verification belongs to the section."""
    table = await _smart_import_table(page, table_name, timeout_ms)
    is_added = await _page_table_is_added(table)
    if is_added is None:
        raise _CandidateError(
            f"Could not determine whether table {table_name!r} is already added."
        )
    if is_added:
        return False
    await table.click()
    return True


async def _inline_editing_toggle(
    page: Page, table_name: str, timeout_ms: int
) -> ElementHandle:
    """Find the inline-editing switch for one table."""
    table_row = page.get_by_text(table_name, exact=True).locator(
        "xpath=ancestor::*[.//input[@role='switch'] "
        "and .//span[normalize-space()='Edit records inline']][1]"
    )
    toggle = await _require_one(
        page,
        table_row.get_by_role("switch"),
        f"Edit records inline switch for {table_name!r}",
        timeout_ms,
    )
    return toggle


async def _ensure_inline_editing(
    page: Page, table_name: str, timeout_ms: int
) -> bool:
    """Apply one inline-editing change without waiting for individual saves."""
    toggle = await _inline_editing_toggle(page, table_name, timeout_ms)
    if await toggle.is_checked():
        return False
    await toggle.click()
    return True


async def smart_import_core(page: Page, settings: Settings) -> ActionReport:
    """Run the inspected Smart Import CORE setup clicks in their captured order."""
    action_name = "smart_import_core"
    report = _new_report(action_name, page)

    try:
        # 5.1. Open the extension and verify its setup panel before configuring it.
        async def open_installation(_: str) -> bool:
            # Opening the extension is navigation; completion is established by
            # the loaded extension frame, rather than a successful click.
            for click_number in range(1, _SMART_IMPORT_INSTALLATION_CLICKS + 1):
                installation = page.get_by_test_id(_SMART_IMPORT_INSTALLATION_TEST_ID)
                button = await _require_one(
                    page, installation.get_by_role("button"),
                    f"Smart Import installation button (click {click_number})",
                    settings.browser_timeout_ms,
                )
                await button.click()
                if click_number < _SMART_IMPORT_INSTALLATION_CLICKS:
                    await page.wait_for_timeout(250)
            return True

        async def installation_is_loaded(_: str) -> bool:
            await _wait_for_smart_import_frame(page, settings.browser_timeout_ms)
            return True

        if not await _run_core_validated_section(
            page, report, "Installation", ("Smart Import CORE frame",),
            open_installation, installation_is_loaded, settings.browser_timeout_ms,
        ):
            return report.finish(page)

        frame = await _wait_for_smart_import_frame(page, settings.browser_timeout_ms)

        async def open_setup(_: str) -> bool:
            setup = await _require_one(
                page, frame.get_by_role("button", name="Setup", exact=True),
                "Smart Import CORE Setup button", settings.browser_timeout_ms,
                exact_text="Setup",
            )
            await setup.click()
            return True

        async def setup_is_open(_: str) -> bool:
            await _require_one(
                page, frame.get_by_text("Extra mappable fields", exact=True),
                "Setup extra mappable fields heading", settings.browser_timeout_ms,
            )
            return True

        if not await _run_core_validated_section(
            page, report, "Setup", ("Extra mappable fields panel",),
            open_setup, setup_is_open, settings.browser_timeout_ms,
        ):
            return report.finish(page)

        # 5.2. Apply and validate all expected fields and linked tables.
        field_types = dict(_SMART_IMPORT_EXTRA_FIELDS)
        extra_fields_section = frame.get_by_text(
            "Extra mappable fields", exact=True
        ).locator("xpath=ancestor::*[.//input[@role='combobox']][1]")
        if not await _run_core_validated_section(
            page, report, "Extra field", tuple(field_types),
            lambda name: _click_smart_import_field(
                page, frame, name, field_types[name], settings.browser_timeout_ms
            ),
            lambda name: _smart_import_field_is_configured(
                extra_fields_section, name, field_types[name]
            ),
            settings.browser_timeout_ms,
        ):
            return report.finish(page)

        async def table_is_added(name: str) -> bool:
            table = await _smart_import_table(page, name, settings.browser_timeout_ms)
            return await _page_table_is_added(table) is True

        if not await _run_core_validated_section(
            page, report, "Linked table", _SMART_IMPORT_LINKED_TABLES,
            lambda name: _ensure_smart_import_table(
                page, name, settings.browser_timeout_ms
            ),
            table_is_added, settings.browser_timeout_ms, wait_for_save=True,
        ):
            return report.finish(page)

        # 5.3. Enable inline editing and verify the complete per-table state.
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(250)
        sidebar = page.get_by_test_id("page-creator-sidebar")
        async def open_inline_configuration(_: str) -> bool:
            configure = await _require_one(
                page,
                sidebar.get_by_role(
                    "button", name="Configure: Edit records inline by table", exact=True
                ),
                "Configure: Edit records inline by table button",
                settings.browser_timeout_ms,
            )
            await configure.click()
            return True

        async def inline_configuration_is_open(_: str) -> bool:
            await _inline_editing_toggle(
                page, "Field Mapping Sessions", settings.browser_timeout_ms
            )
            return True

        if not await _run_core_validated_section(
            page, report, "Inline editing configuration", ("Per-table switches",),
            open_inline_configuration, inline_configuration_is_open,
            settings.browser_timeout_ms,
        ):
            return report.finish(page)

        async def inline_editing_is_enabled(name: str) -> bool:
            toggle = await _inline_editing_toggle(
                page, name, settings.browser_timeout_ms
            )
            return await toggle.is_checked()

        if not await _run_core_validated_section(
            page, report, "Inline editing", _SMART_IMPORT_INLINE_EDIT_TABLES,
            lambda name: _ensure_inline_editing(
                page, name, settings.browser_timeout_ms
            ),
            inline_editing_is_enabled, settings.browser_timeout_ms,
            wait_for_save=True,
        ):
            return report.finish(page)
    except (_CandidateError, PlaywrightError) as exc:
        report.results.append(
            CandidateResult(
                candidate="Smart Import CORE setup sequence",
                outcome=Outcome.FAILED,
                message=str(exc),
                details={"stage_url": page.url},
            )
        )

    return report.finish(page)
