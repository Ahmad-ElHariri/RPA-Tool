"""Command-line entry point for recording and concurrent Airtable runs."""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError

# Keep generated Python bytecode out of the project workspace.
sys.dont_write_bytecode = True

from Backend.helpers import list_actions
from Backend.browser import BrowserLaunchError, BrowserSession, NavigationError
from Backend.config import (
    APP_GROUPS,
    AppConfig,
    Settings,
    _validate_airtable_url,
    configure_logging,
    load_apps,
    resolve_apps_inventory,
)
from Backend.recorder import ClickRecorder, install_recorder, wait_for_recording
from Backend.reporting import generate_excel_report
from Backend.runner import ConcurrentRunner


LOGGER = logging.getLogger(__name__)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


# 1. CLI arguments and explicit targets.
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record Airtable workflows and run safe concurrent actions."
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--apps-file", type=Path, help="App inventory file (default: Apps.json)")
    parser.add_argument("--apps-group", choices=APP_GROUPS, help="Inventory group: plus or core")
    subcommands = parser.add_subparsers(dest="command", required=True)

    record_command = subcommands.add_parser(
        "record", help="Record a workflow using normal clicks"
    )
    record_target = record_command.add_mutually_exclusive_group(required=True)
    record_target.add_argument("--app", help="App name from the selected inventory")
    record_target.add_argument("--url", help="Explicit Airtable URL")
    record_command.add_argument(
        "--label",
        default="page",
        help="Task or step name included in recording filenames",
    )

    def add_run_command(name: str, help_text: str) -> None:
        command = subcommands.add_parser(name, help=help_text)
        command.add_argument("actions", nargs="+", choices=list_actions())
        target = command.add_mutually_exclusive_group()
        target.add_argument("--url", help="Run on one explicit Airtable URL")
        target.add_argument(
            "--app",
            action="append",
            dest="apps",
            help="Run only this named app; may be provided more than once",
        )
        command.add_argument(
            "--concurrency",
            type=_positive_int,
            help="Override the CONCURRENCY setting for this run",
        )

    add_run_command("run", "Run any workflow in the shared helpers catalogue")

    subcommands.add_parser("list-actions", help="List registered action names")
    subcommands.add_parser("list-apps", help="List configured app names")
    return parser


# 2. Target selection and normal-click recording.
def _select_apps(apps: tuple[AppConfig, ...], names: list[str] | None) -> tuple[AppConfig, ...]:
    if not names:
        return apps
    requested = set(names)
    selected = tuple(app for app in apps if app.name in requested)
    missing = requested - {app.name for app in selected}
    if missing:
        available = ", ".join(app.name for app in apps)
        raise ValueError(
            f"Unknown app name(s): {', '.join(sorted(missing))}. Available: {available}"
        )
    return selected


def _record_workflow(
    settings: Settings,
    apps: tuple[AppConfig, ...],
    app_name: str | None,
    explicit_url: str | None,
    label: str = "page",
) -> int:
    if explicit_url:
        target_url = _validate_airtable_url(explicit_url, "Recording URL")
    elif app_name:
        target_url = _select_apps(apps, [app_name])[0].url
    else:
        raise ValueError("Choose one named app or provide an explicit recording URL.")
    matching_app = next((app for app in apps if app.url == target_url), None)
    base_id = re.search(r"/(app[A-Za-z0-9]+)", target_url)
    recording_name = (
        matching_app.name
        if matching_app
        else base_id.group(1)
        if base_id
        else "airtable"
    )
    with BrowserSession(settings) as browser:
        assert browser.context is not None
        recorder = ClickRecorder(settings.recordings_dir, recording_name, label)
        install_recorder(browser.context, recorder)
        page = browser.navigate(target_url)
        LOGGER.info("Recording file: %s", recorder.path)
        try:
            wait_for_recording(page)
        except KeyboardInterrupt:
            LOGGER.info("Recording stopped.")
        finally:
            recorder.finish()
            LOGGER.info("Recording complete: %s", recorder.path)
    return 0


# 3. Workflow execution and Excel reporting.
def _run(
    settings: Settings,
    apps: tuple[AppConfig, ...],
    actions: tuple[str, ...],
    concurrency: int | None,
) -> int:
    runner = ConcurrentRunner(
        settings,
        apps,
        concurrency=concurrency,
    )
    summary = asyncio.run(runner.run(actions))
    report_path = generate_excel_report(summary, settings.reports_dir)
    LOGGER.info("Run %s. Excel report: %s", summary.status, report_path)
    return 0 if summary.ok else 2


# 4. Configuration and command dispatch.
def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = Settings.from_env()
        if args.apps_file or args.apps_group is not None:
            apps_file, apps_group = resolve_apps_inventory(
                args.apps_file or settings.apps_file,
                args.apps_group,
                default_group=settings.apps_group,
            )
            settings = replace(settings, apps_file=apps_file, apps_group=apps_group)
        label = "-".join((args.command, *getattr(args, "actions", ())))
        configure_logging(settings, verbose=args.verbose, label=label)

        if args.command == "list-actions":
            print("\n".join(list_actions()))
            return 0
        apps = load_apps(settings.apps_file, settings.apps_group)
        if args.command == "list-apps":
            print("\n".join(app.name for app in apps))
            return 0
        if args.command == "record":
            return _record_workflow(settings, apps, args.app, args.url, args.label)
        if args.command == "run":
            selected_apps = (
                (AppConfig(name="URL trial", url=_validate_airtable_url(args.url, "Run URL")),)
                if args.url else _select_apps(apps, args.apps)
            )
            return _run(
                settings,
                selected_apps,
                tuple(args.actions),
                args.concurrency,
            )
        raise AssertionError(f"Unhandled command: {args.command}")
    except (ValueError, BrowserLaunchError, NavigationError, PlaywrightError) as exc:
        LOGGER.error("%s", exc)
        return 1
    except Exception:
        LOGGER.exception("Unexpected fatal error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
