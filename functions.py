"""New registered workflows exposed by the launcher."""

from playwright.async_api import Page

from backend.airtable_actions import ActionReport, _register
from backend.config import Settings
from backend.old_core_global_changes import (
    change_request_add_filter as _legacy_change_request_add_filter,
)


# Keep only @_register public workflows here. Put reusable implementation
# details in backend/helpers.py.


@_register(writes_data=True)
async def change_request_add_filter(
    page: Page, settings: Settings
) -> ActionReport:
    """Add the two QA Review status filters to their existing groups."""
    return await _legacy_change_request_add_filter(page, settings)
