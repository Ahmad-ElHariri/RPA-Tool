# Airtable RPA

Record normal Airtable clicks and run registered automation through a separate,
persistent Chrome profile. The desktop launcher and CLI use the same configuration,
workflows, diagnostics, and Excel reports.

## 1. Project structure

```text
Airtable_RPA.pyw                # Desktop Inspect/Run window
Apps.json                      # Separate plus and core app arrays
AGENTS.md                      # All project development rules; no separate skills
Memory/airtable_memory.xlsx     # Local Excel catalogue, patterns, fixes, evidence
Memory/memory.py                # Search, refresh and record project memory
Backend/
    cli.py                     # Command-line parsing and dispatch
    config.py                  # Settings, inventories, timestamps, saved logs
    browser.py                 # Sync/async Chrome lifecycle
    recorder.py                # Ordered click and DOM evidence
    helpers.py                 # Workflow catalogue, results, shared controls
    runner.py                  # App workers and action execution
    reporting.py               # Excel report generation
    workflows/
        __init__.py            # Empty package marker
        activation_assignment.py
        activation_scripts.py
        activation_qa_visibility.py
        assign_change_activator.py
        suggestion_details.py
        push_master_apps.py
        adsets_metrics_sync.py
        change_request_add_filter.py
        smart_import_core.py
        remove_publicis_media_team_signature.py
        hide_suggested_metric.py
        hide_delete_button.py
Artifacts/
    inspections/               # Recorded clicks and DOM evidence
    reports/                   # Excel run results
    logs/                      # Full diagnostic logs
    screenshots/               # Failure screenshots
chrome-profile/                # Local saved Chrome login/session
```

`Artifacts/` and `chrome-profile/` are local runtime folders, ignored by source
control. `.env` and the memory workbook are also local. `AGENTS.md` is the single
AI Development Guide; its conventional filename enables
automatic discovery. It contains roles, evidence rules, repository conventions,
verification, reporting, memory, and data protection. The user performs and records
inspections; Codex reviews the recordings and implements the automation. Detailed
workflow contracts live beside their implementation and in memory. No separate
skills or documentation folders are needed.

## 2. Install and launch

Open PowerShell in this folder and install the dependencies inline:

```powershell
python -m pip install "playwright>=1.45,<2.0" "openpyxl>=3.1,<4.0" tzdata
```

Google Chrome must be installed. Double-click `Airtable_RPA.pyw`, or use:

```powershell
python -B Airtable_RPA.pyw
```

The launcher uses built-in Tkinter; no additional UI packages are needed.
For the first Airtable login, start an inspection, sign in within the automation
Chrome window, and close that entire window. The session remains in
`chrome-profile/`; never copy or share that folder.

## 3. Inspect from a saved app or URL

1. Select **Inspect**. There is no function selector in this view.
2. Choose **Saved app**, select `plus` or `core` from `Apps.json`, then choose
   exactly one row from the app/URL table. Nothing is chosen automatically.
3. Alternatively, choose **Paste URL** and enter the exact Airtable page URL.
4. Click **Inspect page** and perform the complete workflow with normal clicks,
   including intermediate selections that reveal later controls.
5. After the final click has settled, close the automation Chrome window.
6. Use **Open inspection** to review the saved JSON and **Open log** for diagnostics.

Recordings contain actionable elements, regions, ancestors, pointer stacks,
frames, state, and post-click overlays. Read them in click order when building
semantic Playwright locators. Screenshots provide context, not selectors.
There is no ALT-click or snapshot inspection mode, and recordings are not
automatically replayed workflows.

## 4. Run a workflow

1. Select **Run** and choose a **Function** from the compact dropdown. It shows
   the four newest workflows excluding the fixed choices, followed by
   `change_request_add_filter` and `push_master_apps`. These six distinct entries
   update automatically as workflows are added. Dates come from saved edit
   history; unknown dates are labelled explicitly. Use the arrow keys and Enter
   to select, or Esc to dismiss. All twelve workflows remain available in the CLI.
2. Select an **Inventory**: `plus` or `core`, both stored in `Apps.json`.
3. Review the app names and URLs. All entries start selected. Use **Clear** and
   select one explicitly authorized app for a first write trial. Ctrl-click
   selects multiple targets; **Select all** restores the complete selection.
4. Click **Run workflow**. The animated wave and elapsed time show that work is
   active; they do not estimate a completion percentage or impose a time limit.
5. Review **Open report** and **Open log** when it finishes.

Each run creates one Excel workbook. Reports use a five-column overview:
**App**, **Result**, **Message**, **Duration**,
and **Failure Information**. The gray title shows the workflow name; start/end
times and the run date use Lebanon time. Blue headers, colored results and
wrapped messages follow the supplied report style. **Details** preserves full
messages, source states, diagnostic data, URLs and timestamps; failure cells link
to their corresponding detail rows. Multi-action runs name each action in its
overview message. The **Interface publish warnings** sheet remains available.

App workers may run concurrently, but all actions for a given app run serially.
Unprocessed or unverified required changes
remain failures. A failed target may produce a screenshot in `Artifacts/screenshots/`.
Before broader writes, review the smallest authorized trial's report and image.

`unsync_adsets_metrics` selects and right-clicks **Adsets Metrics**, opens
**Update sync configuration**, and removes its single source through the recorded
confirmation. Multiple sources fail. It always attempts the recorded removal
path, without inferring sync state or skipping; missing required controls fail
and are reported. The confirmation states that existing data remains and future syncing
stops. After final **Remove**, the workflow waits five seconds. By explicit user
instruction for this function only, it performs no post-removal verification or
reload. A completed run reports submission and the wait, with the final table
state labelled **unverified**. Other workflows retain their verification rules.

## 5. Read warnings and push results

`push_master_apps` attempts the recorded interface Publish → changed section →
Select all → final Publish sequence once, then publishes to the library and
pushes to Airtable's selected installations. It preserves the selection without
a fixed installation count, unique-name requirement, or requirement that the
library preview repeat the base's display name.

Interface-publication issues are non-failing warnings. The workflow clears the
identified interface publication dialog with its recorded Cancel control when
needed and continues. If library publication and push succeed, the result is
**Success with warnings**. The workbook's **Interface publish warnings** sheet
lists affected apps and their downstream results.

This workflow uses the configured navigation and browser timeouts until the
installation-list **Push updates** button is clicked. After that click,
confirmation, scrolling, and completion verification have no elapsed-time
deadline. It waits for semantic state and logs progress. Actual errors or
browser closure can still prevent verification.

The selected count, footer, and discovered selected rows must agree before
submission. Each selected target must be verified as **Up to date**, a status
captured in live evidence. Unselected bases need not change. Virtualized rows need
not change after each wheel event, and scrolling may pause while updating.
Closing a dialog or losing **Updates available** does not prove completion.
No interface publication or push submission is automatically replayed.

`Assign_Change_Activator` follows Flow Core → Activation → Media Plan details →
Change Requests → Change Request Details. It sets the demonstrated visibility
rule, `Assign Activation is not empty`, skips an existing exact rule, and verifies
persistence after saving and reloading.

## 6. Inventories and configuration

- `Apps.json` stores the two inventories as separate arrays: `plus` and `core`.
- `plus` remains the default. The launcher offers the same two inventory choices.
- `.env` can select another file through `APPS_FILE` and a group through `APPS_GROUP`.
- CLI `--apps-file` and `--apps-group` override these settings for one command.
- Old project paths `plus_apps.json` and `core_apps.json` remain accepted by
  `APPS_FILE` and `--apps-file` as aliases for their corresponding `Apps.json` groups.
  Existing custom inventory files containing one array are also supported.

Names and URLs must be unique within each inventory. The file format is:

```json
{
  "plus": [
    {"name": "Plus market", "url": "https://airtable.com/app..."}
  ],
  "core": [
    {"name": "Core market", "url": "https://airtable.com/app..."}
  ]
}
```

Settings such as `CONCURRENCY`, `HEADLESS`, and runtime directories are loaded
through `Backend/config.py`. Outputs default to `Artifacts/logs/`,
`Artifacts/reports/`, `Artifacts/inspections/`, and `Artifacts/screenshots/`.
Existing overrides pointing to the former built-in locations resolve to the new
folders; custom output paths remain supported. Do not add workflow
timeouts, selection limits, or retry rules without explicit user instructions.

## 7. Saved diagnostics

Each CLI operation saves a timestamped `.log` file, including exceptions and
artifact paths. The launcher has its own log and also captures subprocess output,
including startup errors. **Open log** follows the current operation's announced
log file; it falls back to the launcher log if startup fails before one is created.
The shorter **Logs** panel shows readable milestones and warning/error notices.
Full original output and tracebacks remain in the saved text logs. Inspect and
Run use distinct teal and violet action buttons on rounded, frosted panels.

Logs, inspections, and reports use Lebanon timestamps:
`<descriptive-name>  -  MM-DD__HH.MM`, with numbered suffixes on collisions.
Failure screenshots retain their existing timestamp format.

Logs are local diagnostics, not source files. No automatic retention or deletion
policy is applied. Historical reports, inspections, and saved Chrome login data
are preserved unless deletion is explicitly requested. Never share them or
commit them to source control. Runtime folders are recreated as needed after
an explicitly requested cleanup. Preserve the saved Chrome login profile unless
its deletion is specifically requested.

## 8. Command-line operations

```powershell
python -B -m Backend.cli list-actions
python -B -m Backend.cli list-apps
python -B -m Backend.cli --apps-group core list-apps
python -B -m Backend.cli inspect --url "https://airtable.com/app.../..." --label "task-name"
python -B -m Backend.cli --apps-group core inspect --app "App name" --label "task-name"
python -B -m Backend.cli --apps-file Apps.json --apps-group plus run push_master_apps --app "App name"
python -B -m Backend.cli run function_name --url "https://airtable.com/app.../..."
python -B -m Backend.cli run first_function second_function --url "https://airtable.com/app.../..."
```

Inspection always requires an explicit app or URL. Add `--verbose` before the
subcommand to include debug logging. Every workflow uses the same normal commands:

```powershell
python -B -m Backend.cli list-actions
python -B -m Backend.cli run hide_suggested_metric --url "https://airtable.com/app.../..."
```

## 9. Maintain and validate

Find the complete workflow catalogue in `Backend/helpers.py`. Each of the twelve
tasks has one file in `Backend/workflows/`, with a public async entry point named
after its catalogue key and accepting `(page, settings)`. Task-specific controls
and constants stay beside that task; controls reused across tasks, common result
types, and dispatch live in `helpers.py`. Both `__init__.py` files are empty.
Keep CLI dispatch in `Backend/cli.py` and desktop UI in `Airtable_RPA.pyw`.

To add a workflow, create its task module and append one `ActionDefinition` to
`_ACTIONS` in `helpers.py`, with its module, write flag, and first addition date
in Lebanon time. Append entries in addition order: this breaks same-day ties.
Do not change an addition date when editing a workflow. Entries with unknown
dates sort after dated entries. The launcher calculates its four recent choices
from the catalogue and always appends the two fixed choices without duplicates.
Shared save/validation helpers with different waiting or retry behavior stay
distinct. Use numbered comments for meaningful phases.

Follow **find → validate → act → verify → report**. Use recorded selectors,
preserve live locators across rerenders, and reject ambiguous targets. Ask before
implementing any missing workflow requirement, timeout, recovery, or skip rule.
Existing code and fixtures do not prove that behavior was authorized.

New workflows require inspection, implementation, and a successful verified trial
on one explicitly authorized target before broader runs. Check state before each
change, report already-correct items when skipping is permitted, and verify the
observable result of every action. Report each target's before state, actions or
skips, verification, and timestamped last observed state/status. Failures need a
clear step and reason, expected versus observed state, full saved diagnostics,
and artifact links. See `AGENTS.md` sections 3 through 5 for the complete requirements.

Use focused local checks for code changes; local checks do not replace a live
workflow trial.
Preserve warnings, configured pre-push timeouts, unlimited post-push waiting,
exactly-once submissions, and Airtable's selected targets. These new-workflow
requirements do not request retrofitting existing workflows.

Run only one launcher/CLI browser operation at a time because they share a Chrome
profile. Do not open that profile in a separate Chrome process.

## 10. Project memory in Excel

Open `Memory/airtable_memory.xlsx` and start with **Start here** or **Workflows**.
The workbook has filters, frozen headings, wrapped text, source links and clearly
labelled evidence. It is the memory database; no separate SQLite service or new
package is required. Existing `openpyxl` handles reading and writing.

- **Workflows / Functions:** generated entry points, source locations, static
  references and callers. Verification, Evidence IDs and Notes are maintained
  separately from the generated code catalogue.
- **Patterns:** reusable observations with scope, current-state checks and evidence.
- **Failures & fixes:** symptoms, confirmed or unproven causes, corrections and
  verification. Source-code safeguards are labelled Code observed, not claimed
  as reconstructed historical failures.
- **Evidence:** references and concise findings from surviving inspections,
  reports, logs, source review and this project's conversation.

```powershell
python -B Memory/memory.py search "saving before reload"
python -B Memory/memory.py search "Suggestion Details"
python -B Memory/memory.py show PAT-06
python -B Memory/memory.py show "backend/helpers.py::_ensure_suggestion_details_hidden"
python -B Memory/memory.py refresh
python -B Memory/memory.py record --file <record.json>
```

Search returns ranked keyword matches and linked IDs; it does not understand
synonyms automatically. Try alternative page/control/error terms and follow
Evidence IDs and function references. `--limit 0` displays every matching record.
Current code fingerprints are checked during search even without a refresh.
Existing function IDs remain stable after source moves: an ID may name an old
file. Use its **Source** and **Line** columns for the current location. The catalogue
includes nested workflow modules and keeps their links to historical findings.
They include local imported modules conservatively, so unrelated module changes
can also trigger review. An unchanged fingerprint cannot detect Airtable changes.

The assistant searches memory before workflow development, compares it with the
new inspection, and records investigated failures and verified fixes afterward.
These are development steps, not an automatic background process. Old entries do
not authorize a new operation. Historical trials without a source revision are
labelled accordingly; current fingerprints start at import time.

A record payload can add an observation, failure or Evidence row, or update
allowed fields on a function. Existing IDs merge only supplied fields. Example:

```json
{
  "sheet": "Functions",
  "record": {
    "ID": "backend/helpers.py::_ensure_suggestion_details_hidden",
    "Notes": "Check the recorded Fields popover before reuse; this helper targets Suggestion Details specifically."
  }
}
```

For Patterns and Failures & fixes, supply Topic, Scope, Related functions (stable
IDs separated by newlines), Evidence IDs, and Status, plus the relevant finding
fields visible in Excel. Add evidence before referencing it. Live verified
requires a verification date and a Live trial evidence record describing the
observed result. A changed-code record remains Needs revalidation until an
explicit `"revalidated": true` update accompanies reviewed evidence. Function
verification can similarly be updated with an explicit revalidated payload.

Close Excel before tool updates. Keep sheet names, IDs and row-4 headers stable.
Tool saves restyle managed sheets and preserve other user sheets. Runtime
cleanup does not delete this durable workbook. Keep it local and out of source
control; never embed raw logs, recordings, browser profiles or environment secrets.

## 11. AI guidance and research

Keep the standard `AGENTS.md` filename and give it a descriptive title. Codex
automatically discovers that filename; alternatives require additional configuration.
Keep the guide practical and focused on durable repository rules, with operation
recipes beside the relevant implementation. These choices follow the official
[AGENTS.md discovery guidance](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
and [Codex best practices](https://learn.chatgpt.com/docs/learn/best-practices).

The desktop entry point and memory tool disable bytecode generation for imports;
the desktop app also launches its CLI with `-B`. Use the documented `python -B`
commands to keep Python cache folders from returning during normal project checks.
This uses Python's documented [-B option](https://docs.python.org/3/using/cmdline.html#cmdoption-B).
Historical diagnostic artifacts remain available; there is no automatic cleanup policy.
