"""Workflow: remove_publicis_media_team_signature. Task steps and private controls."""

from __future__ import annotations

import time
from playwright.async_api import ElementHandle, Error as PlaywrightError, Page
from Backend.config import Settings
from Backend.helpers import (
    ActionReport,
    CandidateResult,
    Outcome,
    _CandidateError,
    _new_report,
    _require_one,
)


_AUTOMATION_NAME = "[CORE] Send for Approval"


_EMAIL_ACTION_NAME = "Send an email"


_EMAIL_ACTION_DESCRIPTIONS = (
    "Email to original Briefer (If different to Planner)",
    "Email to Alt Approver",
)


_EMAIL_BODY_MARKERS = ("The media plan for", "View Media Plan")


_SIGNATURE = "Publicis x P&G Media Team"


async def _wait_for_email_editors(
    page: Page, timeout_ms: int
) -> list[ElementHandle]:
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        editors: list[ElementHandle] = []
        for handle in await page.locator(
            '[contenteditable="true"]'
        ).element_handles():
            try:
                text = (await handle.inner_text()).strip()
                if await handle.is_visible() and all(
                    marker in text for marker in _EMAIL_BODY_MARKERS
                ):
                    editors.append(handle)
            except PlaywrightError:
                continue
        if editors:
            return editors
        if time.monotonic() >= deadline:
            raise _CandidateError(
                "The expected email body editor was not found after opening the action."
            )
        await page.wait_for_timeout(250)


async def _wait_for_selected_action(
    page: Page,
    action_card: ElementHandle,
    expected_description: str,
    timeout_ms: int,
) -> None:
    """Verify Airtable marks the clicked workflow node as the focused action."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        try:
            is_focused = await action_card.evaluate(
                "element => Boolean(element.closest('[data-testid=\"focused-workflow-node\"]'))"
            )
            if is_focused:
                return
        except PlaywrightError:
            pass
        if time.monotonic() >= deadline:
            raise _CandidateError(
                f"Airtable did not mark {expected_description!r} as the selected action."
            )
        await page.wait_for_timeout(250)


async def _paragraph_texts(editor: ElementHandle) -> list[str]:
    return await editor.eval_on_selector_all(
        "p",
        "elements => elements.map(e => (e.innerText || e.textContent || '')"
        ".replace(/\\s+/g, ' ').trim()).filter(Boolean)",
    )


async def _remove_signature_from_editor(
    page: Page,
    editor: ElementHandle,
    candidate_name: str,
    settings: Settings,
) -> CandidateResult:
    paragraphs = await _paragraph_texts(editor)
    if not paragraphs:
        return CandidateResult(
            candidate=candidate_name,
            outcome=Outcome.FAILED,
            message="The expected email editor contains no paragraph text.",
        )

    exact_matches = [text for text in paragraphs if text == _SIGNATURE]
    if not exact_matches:
        if _SIGNATURE in await editor.inner_text():
            return CandidateResult(
                candidate=candidate_name,
                outcome=Outcome.FAILED,
                message="The signature exists, but not as an exact standalone paragraph.",
            )
        return CandidateResult(
            candidate=candidate_name,
            outcome=Outcome.SKIPPED,
            message="The signature is already absent.",
        )

    if len(exact_matches) != 1 or paragraphs[-1] != _SIGNATURE:
        return CandidateResult(
            candidate=candidate_name,
            outcome=Outcome.FAILED,
            message="The signature was found in an unexpected position or more than once.",
            details={"exact_occurrences": len(exact_matches), "last_line": paragraphs[-1]},
        )

    target_paragraphs: list[ElementHandle] = []
    for paragraph in await editor.query_selector_all("p"):
        text = " ".join((await paragraph.inner_text()).split())
        if text == _SIGNATURE:
            target_paragraphs.append(paragraph)
    if len(target_paragraphs) != 1:
        return CandidateResult(
            candidate=candidate_name,
            outcome=Outcome.FAILED,
            message="The validated signature paragraph changed before editing.",
        )

    await target_paragraphs[0].evaluate(
        """element => {
            element.scrollIntoView({block: 'center'});
            element.closest('[contenteditable="true"]')?.focus();
            const range = document.createRange();
            range.selectNodeContents(element);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        }"""
    )
    await page.keyboard.press("Backspace")
    await page.keyboard.press("Tab")
    await page.wait_for_timeout(min(1_000, settings.browser_timeout_ms))

    if _SIGNATURE in await editor.inner_text():
        return CandidateResult(
            candidate=candidate_name,
            outcome=Outcome.FAILED,
            message="The deletion was attempted, but verification still found the signature.",
        )
    return CandidateResult(
        candidate=candidate_name,
        outcome=Outcome.SUCCESS,
        message="Removed and verified the final-line signature.",
    )


async def remove_publicis_media_team_signature(
    page: Page, settings: Settings
) -> ActionReport:
    """Remove the exact Publicis signature from both approval email bodies."""
    action_name = "remove_publicis_media_team_signature"
    report = _new_report(action_name, page)

    try:
        topbar = page.locator('header[data-testid="appTopbar"]')
        automations_link = await _require_one(
            page,
            topbar.get_by_role("link", name="Automations", exact=True),
            "Automations top-bar link",
            settings.browser_timeout_ms,
        )
        await automations_link.click()

        automation = await _require_one(
            page,
            page.get_by_role("button", name=_AUTOMATION_NAME, exact=True),
            f"automation named {_AUTOMATION_NAME!r}",
            settings.browser_timeout_ms,
        )
        await automation.click()

        for description in _EMAIL_ACTION_DESCRIPTIONS:
            email_action_locator = page.get_by_role("button").filter(
                has_text=_EMAIL_ACTION_NAME
            ).filter(has_text=description)
            email_action = await _require_one(
                page,
                email_action_locator,
                f"{_EMAIL_ACTION_NAME!r} action card for {description!r}",
                settings.browser_timeout_ms,
                exact_text=f"{_EMAIL_ACTION_NAME} {description}",
            )
            await email_action.click()
            await _wait_for_selected_action(
                page, email_action, description, settings.browser_timeout_ms
            )

            editors = await _wait_for_email_editors(
                page, settings.browser_timeout_ms
            )
            for index, editor in enumerate(editors, start=1):
                report.results.append(
                    await _remove_signature_from_editor(
                        page,
                        editor,
                        f"{description} - email body {index}",
                        settings,
                    )
                )
    except (_CandidateError, PlaywrightError) as exc:
        report.results.append(
            CandidateResult(
                candidate="Airtable automation workflow",
                outcome=Outcome.FAILED,
                message=str(exc),
                details={"stage_url": page.url},
            )
        )

    return report.finish(page)
