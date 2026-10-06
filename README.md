# Airtable Interface Automation

This tool records normal clicks in Airtable and runs verified automation
workflows through a separate, persistent Chrome profile.

## 1. Project structure

```text
main.py                       # CLI entry point
launcher.pyw                  # Double-clickable Inspect/Run window
functions.py                  # New launcher-visible workflows only
apps.json                     # Active app inventory
15-PH-apps.json               # Alternate 15-app inventory
backend/
    airtable_actions.py       # Registry, reports, and element validation
    browser.py                # Sync and async Chrome sessions
    config.py                 # Environment, app, and timestamp settings
    helpers.py                # Reusable helpers for new workflows
    old_core_global_changes.py # Preserved legacy workflows
    recorder.py               # Normal-click DOM recorder
    reporting.py              # Excel report generation
    runner.py                 # Controlled concurrent execution.
```
## 2. One-time installation

Open PowerShell in the repository folder and install the Python packages:

```powershell
python -m pip install "playwright>=1.45,<2.0" "openpyxl>=3.1,<4.0" tzdata
```

The default settings work without a `.env` file. Runtime folders such as
`chrome-profile`, `inspections`, and `reports` are created automatically and
must not be committed.

## 3. First Airtable login

The automation uses its own Chrome profile. Initialize it once:

1. Double-click `launcher.pyw`.
2. Select **Inspect**.
3. Paste one authorized Airtable page URL into **Airtable URL**.
4. Click **Inspect page**.
5. In the Chrome window that opens, sign in to Airtable and wait for the page
   to load completely.
6. Close the entire automation Chrome window.

The Airtable session is now saved locally in `chrome-profile`. Never copy,
share, or commit this folder.

If double-clicking the launcher does not work, open PowerShell in the repository
folder and use this troubleshooting command:

```powershell
python launcher.pyw
```

## 4. Inspect a workflow with the launcher

Inspect before creating a new Airtable workflow:

1. Double-click `launcher.pyw` and select **Inspect**.
2. Paste the exact Airtable URL to inspect.
3. Click **Inspect page**.
4. In Chrome, perform the complete workflow using normal clicks and in the
   exact intended order. Include intermediate selections that reveal later
   controls.
5. Wait briefly after the final click, then close the entire Chrome window.
6. Return to the launcher and click **Open inspection**.

The JSON recording is saved in `inspections`. It records click and DOM evidence;
it is not an automatically replayable workflow. Use it to implement reliable
semantic selectors and final-state checks.

## 5. Run a function with the launcher

Only workflows registered in `functions.py` appear in the launcher.

1. Double-click `launcher.pyw` and select **Run**.
2. Choose the function from **Function**.
3. Choose `apps.json` or `15-PH-apps.json` from **App file**.
4. Select the target apps. All apps are selected by default, so for a first
   trial click **Clear** and select one explicitly authorized app.
5. Click **Run workflow** and leave the launcher open until it finishes.
6. Review the logs, then click **Open report** and check every result.

Use Ctrl-click to select multiple apps, or **Select all** to restore the full
selection. Each run creates one Excel report in `reports`. Failures may also
create a screenshot in `backend/screenshots`.

Before a broader write run, always test the workflow on the smallest explicit
target and review its report and any failure screenshot.

## 6. App inventories

The launcher supports these inventories:

- `apps.json`: the active app list.
- `15-PH-apps.json`: the alternate 15-app list.

Each file contains unique app names and Airtable URLs:

```json
[
  {
    "name": "Market A",
    "url": "https://airtable.com/app..."
  }
]
```

## 7. Terminal-only operations

The launcher intentionally excludes preserved legacy workflows. List and run
them from PowerShell only:

```powershell
python main.py list-old-actions
python main.py run-old hide_suggested_metric --url "https://airtable.com/app.../..."
```

The terminal is also required to run a current function on one explicit URL or
to run several current functions serially:

```powershell
python main.py run function_name --url "https://airtable.com/app.../..."
python main.py run first_function second_function --url "https://airtable.com/app.../..."
```

Optional inventory and registry checks are:

```powershell
python main.py list-apps
python main.py list-actions
```

## 8. Adding a new function

Keep only the public registered workflow in `functions.py`. Put reusable or
lengthy helpers in `backend/helpers.py`. Do not modify
`backend/old_core_global_changes.py` unless legacy maintenance is explicitly
requested.

```python
from playwright.async_api import Page

from backend.airtable_actions import ActionReport, _register
from backend.config import Settings



@_register(writes_data=True)
async def descriptive_action(page: Page, settings: Settings) -> ActionReport:
    ...
```

Build every workflow around **find -> validate -> act -> verify -> report**.
Reject ambiguous targets, skip an already-correct state, and verify persistence
after reload when appropriate. Restart the launcher after changing registered
functions so its function list refreshes.

## 9. Safety rules

- Run only against authorized Airtable apps.
- Never run two launcher or command-line operations at the same time; they use
  the same Chrome profile.
- Do not open the automation `chrome-profile` with a separate Chrome process.
- Do not share or commit `.env`, `chrome-profile`, inspections, reports, caches,
  or failure screenshots. They may contain login or Airtable data.
- Treat any unprocessed or unverified target as a failure.
