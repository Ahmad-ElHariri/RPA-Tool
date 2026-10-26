"""Generate the single user-facing Excel report for an automation run."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from Backend.helpers import Outcome
from Backend.config import LEBANON_TIMEZONE, artifact_path, lebanon_now
from Backend.runner import AppActionExecution, RunSummary


_NAVY = "42B0D5"
_TITLE_GRAY = "BFBFBF"
_LIGHT_BLUE = "EEF5FB"
_GREEN = "E2F0D9"
_YELLOW = "FFF2CC"
_RED = "FCE4D6"
_WHITE = "FFFFFF"
_BORDER = Side(style="thin", color="000000")


# 1. Readable status and diagnostic text.
def _message(execution: AppActionExecution) -> str:
    return "\n".join(
        f"[{item.outcome.value.upper()}] {item.candidate}: {item.message.splitlines()[0] if item.message else ''}"
        for item in sorted(
            execution.report.results,
            key=lambda item: {Outcome.FAILED: 0, Outcome.WARNING: 1}.get(item.outcome, 2),
        )
    )


def _failure_information(execution: AppActionExecution) -> str:
    if execution.report.ok:
        return ""

    information = [
        f"{item.candidate}: {item.message.splitlines()[0] if item.message else 'No reason recorded.'}"
        for item in execution.report.results if item.outcome == Outcome.FAILED
    ]
    if not information:
        information.append("No successful result was recorded.")
    information.append("See Details for full diagnostics.")
    return "\n".join(information)


def _table_header(sheet, row: int, headings: tuple[str, ...], widths: tuple[int, ...]) -> None:
    for column, (heading, width) in enumerate(zip(headings, widths), 1):
        cell = sheet.cell(row, column, heading)
        cell.font = Font(name="Calibri", size=14, bold=True, color=_WHITE)
        cell.fill = PatternFill("solid", fgColor=_NAVY)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(left=_BORDER, right=_BORDER, top=_BORDER, bottom=_BORDER)
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.row_dimensions[row].height = 34
    sheet.freeze_panes = f"A{row + 1}"


def _body_row(sheet, row: int, values: tuple, widths: tuple[int, ...]) -> None:
    lines = 1
    for column, (value, width) in enumerate(zip(values, widths), 1):
        cell = sheet.cell(row, column, value)
        if isinstance(value, str):
            cell.data_type = "s"
        cell.font = Font(name="Calibri", size=11, color="000000")
        cell.fill = PatternFill("solid", fgColor=_LIGHT_BLUE)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = Border(left=_BORDER, right=_BORDER, top=_BORDER, bottom=_BORDER)
        lines = max(lines, sum(max(1, math.ceil(len(line) / max(1, width - 2)))
                               for line in str(value or "").splitlines()))
    sheet.row_dimensions[row].height = min(409, max(45, lines * 15 + 14))


def _run_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=LEBANON_TIMEZONE)
    return timestamp.astimezone(LEBANON_TIMEZONE)


def _details_sheet(workbook: Workbook, summary: RunSummary) -> dict[int, int]:
    """Retain original messages and structured diagnostics without crowding the overview."""
    sheet = workbook.create_sheet("Details")
    sheet.append(("Actions", ", ".join(summary.actions)))
    sheet.append(("Overall result", summary.status, "Concurrency", summary.concurrency))
    sheet.append(("Started (Lebanon)", summary.started_at, "Finished (Lebanon)", summary.finished_at))
    widths = (24, 40, 48, 110, 110)
    _table_header(sheet, 5, ("App", "Action", "Result / item", "Full message", "Diagnostics"), widths)
    row, destinations = 6, {}
    for index, execution in enumerate(summary.executions):
        destinations[index] = row
        for item in execution.report.results or [None]:
            diagnostic = json.dumps({
                "started_at": execution.report.started_at,
                "finished_at": execution.report.finished_at,
                "target_url": execution.report.target_url,
                "final_url": execution.report.final_url,
                "duration_seconds": execution.duration_seconds,
                "screenshot_path": str(execution.screenshot_path) if execution.screenshot_path else None,
                "details": item.details if item else {},
            }, ensure_ascii=False, indent=2, default=str)
            message = item.message if item else "No item results were recorded."
            label = f"[{item.outcome.value.upper()}] {item.candidate}" if item else "No result"
            # Excel limits each cell to 32,767 characters. Keep long diagnostics
            # in labelled continuation rows rather than silently truncating them.
            parts = max(1, math.ceil(len(message) / 30_000), math.ceil(len(diagnostic) / 30_000))
            for part in range(parts):
                suffix = f" (part {part + 1}/{parts})" if parts > 1 else ""
                start, end = part * 30_000, (part + 1) * 30_000
                _body_row(sheet, row, (execution.app.name, execution.action, label + suffix,
                                      message[start:end], diagnostic[start:end]), widths)
                sheet.cell(row, 1).hyperlink = execution.app.url
                sheet.cell(row, 1).font = Font(name="Calibri", size=11, color="0563C1", underline="single")
                row += 1
    if row > 6:
        sheet.auto_filter.ref = f"A5:E{row - 1}"
    sheet.sheet_view.showGridLines = False
    return destinations


# 2. Explicit non-failing interface warning summary.
def _interface_warning_sheet(workbook: Workbook, summary: RunSummary) -> None:
    rows = []
    for execution in summary.executions:
        for result in execution.report.results:
            if not result.details.get("interface_publication_warning"):
                continue

            def downstream(candidate: str) -> str:
                return next((f"{item.outcome.value.upper()}: {item.message}"
                             for item in execution.report.results if item.candidate == candidate),
                            "Not processed or verified.")

            rows.append((execution.app.name, result.details["interface_error"],
                         downstream("Master app library publication"), downstream("Installed base push"),
                         execution.app.url))
    if not rows:
        return
    sheet = workbook.create_sheet("Interface publish warnings")
    sheet.append(("App continued after interface warning", "Interface publication warning",
                  "Library publication", "Installed base push", "App URL"))
    headings = tuple(cell.value for cell in sheet[1])
    widths = (36, 68, 68, 68, 55)
    _table_header(sheet, 1, headings, widths)
    for number, row in enumerate(rows, 2):
        _body_row(sheet, number, row, widths)
        sheet.cell(number, 2).fill = PatternFill("solid", fgColor=_YELLOW)
    sheet.auto_filter.ref = sheet.dimensions


# 3. Formatted workbook and collision-safe output.
def generate_excel_report(summary: RunSummary, output_dir: Path) -> Path:
    """Create exactly one formatted .xlsx workbook for this run."""
    output_dir.mkdir(parents=True, exist_ok=True)
    action_label = "multi-action" if len(summary.actions) > 1 else summary.actions[0]
    safe_action = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in action_label
    ).strip("-")
    report_path = artifact_path(output_dir, safe_action, ".xlsx")
    temporary_path = report_path.with_name(f".{report_path.stem}.tmp.xlsx")

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Run Report"
    workbook.properties.title = "Airtable Automation Run Report"
    workbook.properties.creator = "Airtable Automation"
    workbook.properties.created = lebanon_now().replace(tzinfo=None)

    worksheet.merge_cells("A1:E1")
    title = worksheet["A1"]
    title.value = ", ".join(summary.actions)
    title.font = Font(name="Calibri", size=16, bold=True, color="000000")
    title.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for cells in worksheet["A1:E1"]:
        for cell in cells:
            cell.fill = PatternFill("solid", fgColor=_TITLE_GRAY)
    worksheet.row_dimensions[1].height = 45
    started, finished = _run_timestamp(summary.started_at), _run_timestamp(summary.finished_at)
    for address, value in (("A2", "Start time"), ("B2", started.time().replace(microsecond=0) if started else None),
                           ("A3", "End time"), ("B3", finished.time().replace(microsecond=0) if finished else None),
                           ("D2", "Day of Run"), ("E2", started.date() if started else None)):
        cell = worksheet[address]
        cell.value = value
        cell.font = Font(name="Calibri", size=11, bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    worksheet["B2"].number_format = worksheet["B3"].number_format = "hh:mm:ss"
    worksheet["E2"].number_format = "dd-mm-yyyy"
    worksheet.row_dimensions[2].height = worksheet.row_dimensions[3].height = 45
    worksheet.row_dimensions[4].height = 19
    header_row = 5
    widths = (14, 16, 142, 14, 29)
    _table_header(worksheet, header_row, ("App", "Result", "Message", "Duration", "Failure Information"), widths)
    worksheet["C5"].comment = Comment("Full original messages and diagnostics are preserved in the Details sheet.", "Airtable RPA")
    destinations = _details_sheet(workbook, summary)

    status_fills = {
        "Success": PatternFill("solid", fgColor=_GREEN),
        "Success with warnings": PatternFill("solid", fgColor=_YELLOW),
        "Skipped": PatternFill("solid", fgColor=_YELLOW),
        "Failed": PatternFill("solid", fgColor=_RED),
    }
    for row_number, execution in enumerate(summary.executions, start=header_row + 1):
        result = execution.report.status
        values = (
            execution.app.name,
            result,
            (f"{execution.action}: " if len(summary.actions) > 1 else "") + _message(execution),
            execution.duration_seconds,
            _failure_information(execution),
        )
        _body_row(worksheet, row_number, values, widths)
        app_cell = worksheet.cell(row=row_number, column=1)
        app_cell.hyperlink = execution.app.url
        app_cell.fill = PatternFill("solid", fgColor=_WHITE)
        app_cell.font = Font(name="Calibri", size=11, color="0563C1", underline="single")
        app_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        result_cell = worksheet.cell(row=row_number, column=2)
        result_cell.fill = status_fills[result]
        result_cell.font = Font(name="Calibri", size=11, bold=True)
        result_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        duration = worksheet.cell(row=row_number, column=4)
        duration.number_format = '0.00 "s"'
        duration.alignment = Alignment(horizontal="center", vertical="center")
        if not execution.report.ok:
            failure = worksheet.cell(row_number, 5)
            failure.hyperlink = f"#'Details'!A{destinations[row_number - 6]}"
            failure.font = Font(name="Calibri", size=11, color="0563C1", underline="single")
    if summary.executions:
        worksheet.auto_filter.ref = f"A{header_row}:E{header_row + len(summary.executions)}"
    worksheet.print_area = f"A1:E{max(5, header_row + len(summary.executions))}"
    worksheet.page_setup.orientation = "landscape"
    worksheet.page_setup.fitToWidth = 1
    worksheet.page_setup.fitToHeight = 0
    worksheet.sheet_properties.pageSetUpPr.fitToPage = True
    worksheet.print_title_rows = f"1:{header_row}"

    _interface_warning_sheet(workbook, summary)
    workbook.save(temporary_path)
    temporary_path.replace(report_path)
    return report_path
