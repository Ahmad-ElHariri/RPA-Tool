"""Configure the Activation assignment and reset scripts."""

from __future__ import annotations

from playwright.async_api import Error as PlaywrightError, Page
from Backend.config import Settings
from Backend.helpers import (
    ActionReport,
    _ASSIGNMENT_AUTOMATION,
    _CandidateError,
    _RESET_AUTOMATION,
    _click,
    _configure_assignment_automation,
    _configure_reset_automation,
    _new_report,
    _open_automation,
    _workflow_failure,
)


async def _open_automations(page: Page, timeout_ms: int) -> None:
    topbar = page.locator('header[data-testid="appTopbar"]')
    await _click(
        page,
        topbar.get_by_role("link", name="Automations", exact=True),
        "Automations link",
        timeout_ms,
    )


async def configure_activation_automation_scripts(page: Page, settings: Settings) -> ActionReport:
    """Configure the two recorded Activation button automations."""
    action_name = 'configure_activation_automation_scripts'
    report = _new_report(action_name, page)
    timeout_ms = settings.browser_timeout_ms
    try:
        if "/automations" not in page.url:
            await _open_automations(page, timeout_ms)

        reset_canvas = await _open_automation(
            page, _RESET_AUTOMATION, timeout_ms
        )
        if not await _configure_reset_automation(
            page, report, reset_canvas, timeout_ms
        ):
            return report.finish(page)

        assignment_canvas = await _open_automation(
            page, _ASSIGNMENT_AUTOMATION, timeout_ms
        )
        await _configure_assignment_automation(
            page, report, assignment_canvas, timeout_ms
        )
    except (_CandidateError, PlaywrightError) as exc:
        _workflow_failure(page, report, 'Activation automation scripts workflow', exc)
    return report.finish(page)
