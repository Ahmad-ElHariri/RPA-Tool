# AI Development Guide

This is the repository-wide working agreement for Codex and other coding agents.
Keep the conventional `AGENTS.md` filename so supported tools discover it automatically.
Keep durable project rules here, usage instructions in the numbered README, and
workflow-specific requirements beside their implementation and in project memory.

## 1. Roles, scope, and evidence

- The user performs inspections: they open Inspect, demonstrate the complete
  workflow with normal clicks, and close the automation Chrome window.
- Codex reviews the user's saved recording and requirements, implements the
  automation, and validates only the targets and operations already authorized.
  Codex must not perform or invent the user's inspection. Launch the recorder
  on the user's behalf only when explicitly requested.
- Existing code, fixtures, documentation, memory, and observed defaults provide
  context; they do not authorize targets, writes, retries, recovery, or deletion.
- Resolve meaningful missing requirements before implementing dependent behavior.
  Continue independent authorized work while awaiting clarification; silence is
  not approval. Routine implementation choices do not require renewed permission.
- Preserve behavior during naming, structure, and UI refactors. Review every new
  branch against user instructions or current evidence. Report uncertainty clearly.

## 2. Project map and local commands

- `Airtable_RPA.pyw`: desktop Inspect/Run application.
- `Backend/cli.py`: CLI parsing and dispatch; run it as `python -B -m Backend.cli`.
- `Backend/workflows/__init__.py`: compact current workflow registrations.
- `Backend/workflows/`: one implementation module per current workflow.
- `Backend/helpers.py`: controls, navigation, and validation shared by workflows.
- Other `Backend/` modules own configuration, browser lifecycle, recording,
  registration, execution, and reporting.
- Preserve the legacy module's contents unchanged unless legacy maintenance is
  explicitly authorized. Legacy workflows remain terminal-only.
- `Apps.json`: separate `plus` (default) and `core` inventories. Keep their names,
  URLs, ordering, selection behavior, and configured overrides intact.
- `Memory/`: the searchable Excel history and its maintenance tool.
- `Artifacts/`: local inspections, reports, logs, and failure screenshots.
- `chrome-profile/`: the user's persistent local login/session; preserve it.

```powershell
python -B Airtable_RPA.pyw
python -B -m Backend.cli list-actions
python -B -m Backend.cli list-old-actions
python -B -m Backend.cli --apps-group core list-apps
python -B Memory/memory.py search "<task, page, helper, or error>"
```

Use one project browser operation at a time: the CLI and desktop app share a
Chrome profile. Keep setup dependencies inline in README; do not add dependency
files, editor configuration, skills, or additional infrastructure without a need
within the authorized task.

## 3. Read recordings before implementing workflows

- Search memory first, then read the complete relevant JSON recording in
  `Artifacts/inspections/` in click order. A recording demonstrates steps;
  its example values do not restrict other apps or authorize extra behavior.
- Use actionable elements, regions, ancestors, pointer stacks, frames, state,
  and post-click overlays to construct semantic Playwright locators. Screenshots
  provide context rather than selectors. There is no ALT-click or snapshot mode.
- Preserve demonstrated intermediate selections, fields, and final text. Do not
  substitute a shortcut or validation for a required recorded action.
- Prefer roles, accessible names, stable IDs, test IDs, exact text, and scoped
  regions. Reject ambiguous targets; avoid coordinates, generated classes, and
  arbitrary positional selection. Request missing DOM evidence when necessary.
- Keep live locators across navigation and rerenders. Reacquire changed controls;
  account for collapsed, delayed, virtualized, off-screen, and framed content.

## 4. Implement and verify observable behavior

- Follow find -> validate -> act -> verify -> report. Check semantic state before
  changing it. Skip an already-correct state only when the workflow permits it;
  report the evidence. Preserve explicitly required actions and submissions.
- Verify the observable result of each action before continuing. A successful
  click call or `domcontentloaded` does not establish the desired application state.
  Verify save completion and reload persistence where appropriate.
- Reuse shared section validation for multi-item work. Validate the entire expected
  state and retry only unresolved items where retries are already authorized.
  Never blindly toggle, repeat a submission, or duplicate a partial write.
- Recover partial work only when uniquely identifiable and explicitly authorized;
  otherwise report the ambiguity and remaining work.
- Preserve each workflow's timeout and waiting semantics, selected targets,
  retry rules, submission counts, and warning/failure classification. Consult its
  implementation contract and evidence rather than generalizing an exception.
- A new workflow requires the user's inspection, implementation, an authorized
  live trial, review/correction, and verified final state. Restate the operation
  before a write trial and use one explicitly authorized app or URL. Review its
  report and failure screenshot before broader runs.
- For structural changes, use focused import, discovery, routing, and artifact
  checks. Do not perform Airtable writes to validate a refactor or populate memory.
  Local checks do not establish live workflow success. Report incomplete validation.
- Keep functions small and responsibilities clear. Use numbered comments for
  meaningful phases or non-obvious safety decisions. Do not recreate a deleted
  test suite or add tests that merely restate reversible implementation details.

## 5. Reports, diagnostics, and user experience

- For each target in a new workflow, report its before state, actions/skips and
  reasons, verification evidence, remaining work, and last observed state, URL,
  and Lebanon timestamp. Include the last observed Airtable status in Excel when
  available; label unavailable or unobserved state explicitly. Never infer it.
- Failures identify the target, step, expected versus observed state, clear reason,
  and unprocessed work. Save full exceptions and artifact paths in text logs,
  link diagnostics in reports, and capture a failure screenshot when possible.
- Preserve workflow-specific non-failing warnings and downstream outcomes.
  These future-workflow requirements do not request retrofitting existing flows.
- Inspect requires an explicit URL or one explicitly selected saved app. Never
  choose the first app automatically or introduce a workflow selector for Inspect.
  Run keeps app/URL columns and defaults to selecting all entries in its inventory.
- Keep the desktop Logs panel concise while retaining original full diagnostics
  in saved logs. Filtering must not change results or artifact discovery. Artifact
  buttons must follow files announced by the current operation.
- Use the central Lebanon time utility consistently. Inspection, report, and log
  filenames use `<descriptive-name>  -  MM-DD__HH.MM` with numbered collisions.
  Preserve the existing failure-screenshot naming format.

## 6. Memory and knowledge maintenance

- Before new features, refactors, or workflow corrections, search
  `Memory/airtable_memory.xlsx` using the memory tool. Follow relevant IDs with
  `show`, inspect exact callers and linked evidence, and try alternative terms.
  A top search match is not proof that an old cause applies.
- Compare reused patterns with current scope and DOM evidence. Distinguish source
  review, inspection evidence, local checks, and live verification. A successful
  skip path does not verify a write path; unchanged code does not prove an unchanged UI.
- After code changes, refresh the catalogue while preserving notes and history.
  Record investigated symptoms, uncertain or confirmed causes, fixes, scope, and
  actual verification results. Preserve contradictory findings as separate records.
- Use `record --file <record.json>` for findings and allowed function metadata.
  Add evidence before referencing it. Use `revalidated: true` only after reviewing
  changed code against new evidence; live verification additionally requires a
  scoped observed live trial and date.
- Keep workbook IDs, sheet names, row-4 headers, and allowed user notes stable.
  Existing IDs survive source moves; use Source and Line for current locations.
  Maintain relocation mappings and recursive package discovery.
- Close the workbook before updates. Keep original recordings, logs, browser
  profiles, and secrets outside memory. Do not reconstruct unavailable evidence
  or imply that memory maintenance is a background monitoring service.

```powershell
python -B Memory/memory.py show "<ID>"
python -B Memory/memory.py refresh
python -B Memory/memory.py record --file "<record.json>"
```

## 7. Data protection and completion

- Keep `Artifacts/`, `.env`, browser profiles, caches, virtual environments, and
  the memory workbook local and excluded from source control. Do not log secrets
  or copy/share runtime data and login profiles.
- Preserve historical reports, recordings, diagnostics, screenshots, profiles,
  and the memory workbook unless their deletion is explicitly requested. Do not
  introduce automatic artifact deletion or retention rules.
- Use `python -B` during development checks to avoid creating bytecode caches.
- Before finishing, review changes and run focused checks appropriate to scope.
  Report what changed, what was actually verified, and material limits. Never
  claim live success from a local fixture or from a click returning successfully.
