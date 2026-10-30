"""Desktop entry point for recording and running Airtable workflows."""

import logging
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

# Keep generated Python bytecode out of the project workspace.
sys.dont_write_bytecode = True

from Backend.helpers import action_added_on, launcher_actions, list_actions
from Backend.config import (
    APP_GROUPS, APPS_FILE, PROJECT_ROOT, AppConfig, Settings, _validate_airtable_url,
    configure_logging, load_apps,
)

ROOT = PROJECT_ROOT
LOGGER = logging.getLogger(__name__)
ACCENT, INK, MUTED, BACKGROUND = "#087f8c", "#1d304b", "#64758b", "#e8eff8"
GLASS, LINE, RUN = "#f5f9fd", "#ffffff", "#6355bd"


def readable_event(line: str) -> tuple[str, str] | None:
    """Show operation milestones; keep raw diagnostics in the saved text logs."""
    record = re.match(r"^\S+ (DEBUG|INFO|WARNING|ERROR|CRITICAL) [\w.]+: (.*)$", line.rstrip())
    if not record:
        return None
    level, message = record.groups()
    if message.startswith("Run ") and "Excel report: " in message:
        result = message.split(". Excel report:", 1)[0].removeprefix("Run ")
        return f"Run finished: {result.lower()}. Report saved.", "file"
    if level in {"ERROR", "CRITICAL"}:
        return "An error occurred. Open the report and log for the reason.", "error"
    if level == "WARNING":
        if message.startswith("Interface publication warning"):
            return "Interface publishing raised a warning; continuing to the library and push.", "warning"
        return "A warning was recorded. Review the report and log.", "warning"
    if message.startswith("Recorder ready."):
        return "Chrome is ready. Perform the workflow, then close Chrome to save.", ""
    if message.startswith("Recording complete:"):
        return "Recording saved. Use Open recording to review it.", "file"
    if message.startswith("Running ") and " for app " in message:
        return f"Working on {message.split(' for app ', 1)[1]}.", ""
    if message.startswith("Finished ") and " for app " in message:
        match = re.match(r"Finished .+ for app (.+) in [\d.]+s \((ok|failed)\)$", message)
        if match:
            name, result = match.groups()
            return (f"{name}: processing finished; see the report for its outcome.", "") if result == "ok" else (
                f"{name}: failed. Open the report for the reason.", "error")
    return None


# 1. Validate explicit targets before starting the command-line process.
def load_inventory(group: str) -> tuple[AppConfig, ...]:
    if group not in APP_GROUPS:
        raise ValueError(f"Choose {' or '.join(APP_GROUPS)}.")
    return load_apps(ROOT / APPS_FILE, group)


def build_arguments(mode: str, function: str, url: str, app_names: tuple[str, ...]) -> list[str]:
    if mode == "Record Workflow":
        if url:
            if app_names:
                raise ValueError("Choose a saved app or paste a URL, rather than both.")
            return ["record", "--url", _validate_airtable_url(url, "Recording URL")]
        if len(app_names) != 1:
            raise ValueError("Choose one app to record, or switch to Paste URL.")
        return ["record", "--app", app_names[0]]
    if mode != "Run" or function not in list_actions():
        raise ValueError("Choose a registered function to run.")
    if not app_names:
        raise ValueError("Select at least one app.")
    return ["run", function, *(arg for name in app_names for arg in ("--app", name))]


# 2. Animate a traveling wave without implying progress or a deadline.
class ActivityWave(tk.Canvas):
    def __init__(self, parent) -> None:
        super().__init__(parent, width=56, height=30, background=GLASS, highlightthickness=0)
        self.bars = [self.create_line(7 + index * 10, 12, 7 + index * 10, 18,
                                     fill="#bac9da", width=5, capstyle="round") for index in range(5)]
        self.active, self.phase, self.timer = False, 0, None
        self.color = ACCENT
        self.stop()

    def start(self, color: str = ACCENT) -> None:
        self.stop()
        self.active, self.color = True, color
        self.tick()

    def tick(self) -> None:
        for index, bar in enumerate(self.bars):
            height = 4 + 15 * (0.5 + 0.5 * math.sin(self.phase - index * 0.8))
            self.coords(bar, 7 + index * 10, 15 - height / 2, 7 + index * 10, 15 + height / 2)
            self.itemconfigure(bar, fill=self.color)
        self.phase += 0.18
        self.timer = self.after(60, self.tick) if self.active else None

    def stop(self, color: str = "#b7c9d7") -> None:
        self.active = False
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        for index, bar in enumerate(self.bars):
            self.coords(bar, 7 + index * 10, 13, 7 + index * 10, 17)
            self.itemconfigure(bar, fill=color)


class GlassPanel(tk.Canvas):
    """Rounded frosted surface with a white rim and a soft offset shadow."""
    def __init__(self, parent, padding: int = 20) -> None:
        super().__init__(parent, height=1, background=BACKGROUND, highlightthickness=0, borderwidth=0)
        self.padding = padding
        self.content = ttk.Frame(self, style="Card.TFrame")
        self.shadow = self.create_polygon(0, 0, 1, 0, 1, 1, smooth=True, fill="#d8e2ef", outline="")
        self.surface = self.create_polygon(0, 0, 1, 0, 1, 1, smooth=True, fill=GLASS, outline=LINE, width=2)
        self.host = self.create_window(padding, padding, window=self.content, anchor="nw")
        self.bind("<Configure>", self._resize)
        self.content.bind("<Configure>", self._fit_height)
        self.after_idle(self._fit_height)

    @staticmethod
    def _corners(x, y, right, bottom):
        radius = 22
        return (x + radius, y, right - radius, y, right, y, right, y + radius,
                right, bottom - radius, right, bottom, right - radius, bottom,
                x + radius, bottom, x, bottom, x, bottom - radius, x, y + radius, x, y)

    def _fit_height(self, _event=None) -> None:
        requested = self.content.winfo_reqheight() + self.padding * 2 + 5
        if self.winfo_pixels(self.cget("height")) != requested:
            self.configure(height=requested)

    def _resize(self, event) -> None:
        self.coords(self.shadow, *self._corners(3, 5, event.width - 2, event.height - 1))
        self.coords(self.surface, *self._corners(1, 1, event.width - 5, event.height - 6))
        self.itemconfigure(self.host, width=max(1, event.width - self.padding * 2 - 4))
        self._fit_height()


class FunctionSelector(ttk.Combobox):
    """Compact native dropdown; display dates without changing dispatch names."""

    def __init__(self, parent, variable: tk.StringVar, choices) -> None:
        choices = tuple(choices)
        self.variable = variable
        self.names = tuple(name for name, _ in choices)
        self.labels = tuple(
            f"{name}  |  {added.strftime('%d %b %Y') if added else 'Date unrecorded'}"
            for name, added in choices
        )
        super().__init__(parent, values=self.labels, state="readonly",
                         width=60, height=6, font=("Segoe UI", 10))
        self.bind("<<ComboboxSelected>>", self._choose)
        self._selection_trace = variable.trace_add("write", self._selected_changed)
        self._selected_changed()

    def _selected_changed(self, *_args) -> None:
        name = self.variable.get()
        self.set(self.labels[self.names.index(name)] if name in self.names else "")

    def _choose(self, _event=None) -> None:
        index = self.current()
        if index >= 0:
            self.variable.set(self.names[index])

    def destroy(self) -> None:
        self.variable.trace_remove("write", self._selection_trace)
        super().destroy()


class Launcher:
    def __init__(self, window: tk.Tk) -> None:
        self.window, self.settings = window, Settings.from_env()
        self.launcher_log = configure_logging(self.settings, label="launcher")
        self.events, self.busy, self.warnings = queue.Queue(), False, False
        self.started = None
        self.mode = tk.StringVar(value="Record Workflow")
        self.source = tk.StringVar(value="Saved app")
        self.inventory = tk.StringVar(value=APP_GROUPS[0])
        self.function, self.url = tk.StringVar(), tk.StringVar()
        self.status, self.selection_count = tk.StringVar(value="Ready"), tk.StringVar()
        self.recording_count = tk.StringVar(value="Choose one app")
        self.last_event = None
        self.apps: tuple[AppConfig, ...] = ()
        self.artifacts = dict(recording=None, report=None, log=self.launcher_log)
        self.fields, self.controls, self.artifact_buttons = {}, [], {}
        window.title("Airtable RPA")
        window.geometry("1060x790")
        window.minsize(900, 760)
        window.configure(background=BACKGROUND)
        window.option_add("*Font", ("Segoe UI", 10))
        self._theme()
        self._layout()
        self.reload_apps()
        self.refresh()
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.after(100, self.poll)

    # 3. Share the theme and field builders across both operation views.
    def _theme(self) -> None:
        style = ttk.Style(self.window)
        style.theme_use("clam")
        settings = {
            "TFrame": dict(background=BACKGROUND),
            "Card.TFrame": dict(background=GLASS),
            "TLabel": dict(background=GLASS, foreground=INK),
            "Muted.TLabel": dict(foreground=MUTED, font=("Segoe UI", 9)),
            "TEntry": dict(padding=9, fieldbackground="#f7f9fc", bordercolor="#dbe4ee"),
            "TCombobox": dict(padding=8, fieldbackground="#f7f9fc", background="#eaf0f6",
                              bordercolor="#dbe4ee", lightcolor="#dbe4ee", darkcolor="#dbe4ee", arrowcolor=ACCENT),
            "TButton": dict(padding=(13, 8), background="#edf3f7", foreground=INK, borderwidth=0),
            "RecordWorkflow.TButton": dict(padding=(24, 11), background=ACCENT,
                                    foreground="white", font=("Segoe UI", 10, "bold")),
            "Run.TButton": dict(padding=(24, 11), background=RUN,
                                    foreground="white", font=("Segoe UI", 10, "bold")),
            "Pill.TRadiobutton": dict(padding=(20, 10), background="#edf3f7",
                                      foreground=MUTED, font=("Segoe UI", 10, "bold")),
            "Treeview": dict(rowheight=28, background="#f8fafc", fieldbackground="#f8fafc",
                             foreground=INK, borderwidth=0),
            "Treeview.Heading": dict(background="#eaf0f6", foreground=MUTED,
                                     padding=7, relief="flat", borderwidth=0, font=("Segoe UI", 9, "bold")),
        }
        for name, options in settings.items():
            style.configure(name, **options)
        style.layout("Pill.TRadiobutton", [("Radiobutton.padding", {
            "children": [("Radiobutton.label", {"sticky": "nswe"})],
        })])
        style.map("Pill.TRadiobutton", background=[("selected", "#dce9f4"), ("active", "#e4edf6")],
                  foreground=[("selected", INK)])
        for name, color, tint in (("RecordWorkflow", ACCENT, "#dceff1"), ("Run", RUN, "#e8e4f8")):
            style.map(f"{name}.Pill.TRadiobutton", background=[("selected", tint)],
                      foreground=[("selected", color)])
        for name, color in (("RecordWorkflow.TButton", "#066673"), ("Run.TButton", "#50439f")):
            style.map(name, background=[("disabled", "#ccd5e2"), ("active", color)],
                      foreground=[("disabled", "#6b7c91")])
        style.map("Treeview", background=[("selected", "#d9f0f2")], foreground=[("selected", "#075966")])
        style.map("TCombobox", fieldbackground=[("readonly", "#f7f9fc")])

    def _field(self, parent, key: str, label: str, row: int):
        field = ttk.Frame(parent, style="Card.TFrame")
        field.grid(row=row, column=0, sticky="ew", pady=4)
        field.columnconfigure(1, weight=1)
        ttk.Label(field, text=label, width=14, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="nw", pady=9,
        )
        self.fields[key] = field
        return field

    def _choices(self, parent, variable, values):
        for value in values:
            style = value.replace(" ", "") + ".Pill.TRadiobutton" if variable is self.mode else "Pill.TRadiobutton"
            button = ttk.Radiobutton(parent, text=value, value=value, variable=variable,
                                     style=style,
                                     command=self.refresh)
            button.pack(side="left", padx=(0, 5))
            self.controls.append((button, "normal"))

    def _layout(self) -> None:
        body = ttk.Frame(self.window, padding=20)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)
        header = ttk.Frame(body)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        mark = tk.Canvas(header, width=44, height=44, background=BACKGROUND, highlightthickness=0)
        mark.pack(side="left", padx=(0, 12))
        for x, y, color in ((5, 8, ACCENT), (19, 8, RUN), (5, 23, "#6e9fc0")):
            mark.create_rectangle(x, y, x + 10, y + 10, fill=color, outline="")
        ttk.Label(header, text="Airtable RPA", background=BACKGROUND, foreground=INK,
                  font=("Segoe UI", 23, "bold")).pack(side="left")
        panel = GlassPanel(body)
        panel.grid(row=1, column=0, sticky="ew")
        card = panel.content
        card.columnconfigure(0, weight=1)
        modes = ttk.Frame(card, style="Card.TFrame")
        modes.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._choices(modes, self.mode, ("Record Workflow", "Run"))
        self.button = ttk.Button(modes, command=self.start, style="RecordWorkflow.TButton")
        self.button.pack(side="right")
        functions = launcher_actions()
        field = self._field(card, "function", "Function", 1)
        self.function_box = FunctionSelector(field, self.function, [(name, action_added_on(name)) for name in functions])
        self.function_box.grid(row=0, column=1, sticky="w")
        if functions:
            self.function.set(min(functions))
        field = self._field(card, "source", "Record from", 2)
        choices = ttk.Frame(field, style="Card.TFrame")
        choices.grid(row=0, column=1, sticky="w")
        self._choices(choices, self.source, ("Saved app", "Paste URL"))
        field = self._field(card, "inventory", "Inventory", 3)
        self.inventory_box = ttk.Combobox(field, textvariable=self.inventory, values=APP_GROUPS, state="readonly")
        self.inventory_box.grid(row=0, column=1, sticky="ew")
        self.inventory_box.bind("<<ComboboxSelected>>", self.reload_apps)
        self.recording_tree = self._app_picker(card, "recording_apps", "App to record", 4, single=True)
        field = self._field(card, "url", "Airtable URL", 5)
        self.url_entry = ttk.Entry(field, textvariable=self.url)
        self.url_entry.grid(row=0, column=1, sticky="ew")
        self.controls += [(widget, "readonly") for widget in (self.function_box, self.inventory_box)]
        self.controls.append((self.url_entry, "normal"))
        self.apps_tree = self._app_picker(card, "apps", "Target apps", 6)
        self._activity(body)
        links = ttk.Frame(body, padding=(0, 12))
        links.grid(row=3, column=0, sticky="new")
        for kind, label in (("recording", "Open recording"), ("report", "Open report"), ("log", "Open log")):
            button = ttk.Button(links, text=label, command=lambda key=kind: self.open_artifact(key))
            button.pack(side="left", padx=(0, 8))
            self.artifact_buttons[kind] = button

    def _app_picker(self, card, key, label, row, *, single=False):
        field = self._field(card, key, label, row)
        picker = ttk.Frame(field, style="Card.TFrame")
        picker.grid(row=0, column=1, sticky="ew")
        picker.columnconfigure(0, weight=1)
        tree = ttk.Treeview(picker, columns=("name", "url"), show="headings", height=5,
                            selectmode="browse" if single else "extended")
        for column, label, width in (("name", "APP", 190), ("url", "AIRTABLE URL", 490)):
            tree.heading(column, text=label, anchor="w")
            tree.column(column, width=width, minwidth=120)
        scrollbar = ttk.Scrollbar(picker, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=0, column=0, sticky="ew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree.bind("<<TreeviewSelect>>", self._selection_changed)
        tools = ttk.Frame(picker, style="Card.TFrame")
        tools.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        actions = [("Clear", lambda: tree.selection_set(()))]
        if not single:
            actions.insert(0, ("Select all", self.select_all_apps))
        for text, command in actions:
            button = ttk.Button(tools, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            self.controls.append((button, "normal"))
        ttk.Label(tools, textvariable=self.recording_count if single else self.selection_count,
                  style="Muted.TLabel").pack(side="right")
        return tree

    # 4. Keep the activity view responsive while the subprocess streams diagnostics.
    def _activity(self, body) -> None:
        panel = GlassPanel(body, padding=16)
        panel.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        activity = panel.content
        top = ttk.Frame(activity, style="Card.TFrame")
        top.pack(fill="x", pady=(0, 8))
        self.indicator = ActivityWave(top)
        self.indicator.pack(side="left", padx=(0, 8))
        ttk.Label(top, text="Logs", font=("Segoe UI", 11, "bold")).pack(side="left")
        self.status_label = ttk.Label(top, textvariable=self.status, style="Muted.TLabel")
        self.status_label.pack(side="right")
        self.output = ScrolledText(activity, height=4, state="disabled", wrap="word", background="#e8f0f8",
                                   foreground=INK, font=("Segoe UI", 10), relief="flat", borderwidth=0,
                                   highlightthickness=0, padx=12, pady=10)
        self.output.pack(fill="both", expand=True)
        for tag, color in (("error", "#ad3549"), ("warning", "#8a5c11"), ("file", "#086d79")):
            self.output.tag_configure(tag, foreground=color)

    def reload_apps(self, _event=None) -> None:
        for tree in (self.apps_tree, self.recording_tree):
            tree.delete(*tree.get_children())
        try:
            self.apps = load_inventory(self.inventory.get())
        except ValueError as exc:
            self.apps = ()
            LOGGER.error("Could not load inventory: %s", exc)
            self.append(f"Inventory: {exc}\n")
        for app in self.apps:
            for tree in (self.apps_tree, self.recording_tree):
                tree.insert("", "end", iid=app.name, values=(app.name, app.url))
        self.select_all_apps()

    def select_all_apps(self) -> None:
        self.apps_tree.selection_set(self.apps_tree.get_children())
        self._selection_changed()

    def _selection_changed(self, _event=None) -> None:
        self.selection_count.set(f"{len(self.apps_tree.selection())} / {len(self.apps)} selected")
        self.recording_count.set("1 app selected" if self.recording_tree.selection() else "Choose one app")

    def selected_app_names(self) -> tuple[str, ...]:
        selected = self.apps_tree.selection()
        return tuple(app.name for app in self.apps if app.name in selected)

    def refresh(self) -> None:
        recording = self.mode.get() == "Record Workflow"
        visible = ({"source", "inventory", "recording_apps"} if self.source.get() == "Saved app"
                   else {"source", "url"}) if recording else {"function", "inventory", "apps"}
        for name, field in self.fields.items():
            field.grid() if name in visible else field.grid_remove()
        for control, state in self.controls:
            control.configure(state="disabled" if self.busy else state)
        self.apps_tree.configure(selectmode="none" if self.busy else "extended")
        self.recording_tree.configure(selectmode="none" if self.busy else "browse")
        self.button.configure(text="Record Workflow" if recording else "Run workflow",
                              style="RecordWorkflow.TButton" if recording else "Run.TButton",
                              state="disabled" if self.busy else "normal")
        self.update_links()

    def append(self, text: str, tag: str = "") -> None:
        self.output.configure(state="normal")
        self.output.insert("end", text, tag)
        self.output.see("end")
        self.output.configure(state="disabled")

    def start(self) -> None:
        if self.busy:
            return
        try:
            recording = self.mode.get() == "Record Workflow"
            url, names = self.url.get().strip(), self.selected_app_names()
            if recording and self.source.get() == "Saved app":
                url, names = "", tuple(self.recording_tree.selection())
            elif recording:
                names = ()
            args = ["--apps-file", str(ROOT / APPS_FILE), "--apps-group", self.inventory.get(),
                    *build_arguments(self.mode.get(), self.function.get(), url, names)]
        except ValueError as exc:
            messagebox.showerror("Check your selection", str(exc), parent=self.window)
            return
        self.artifacts = dict(recording=None, report=None, log=self.launcher_log)
        self.busy, self.warnings, self.started = True, False, time.monotonic()
        self.last_event = None
        self.indicator.start(ACCENT if recording else RUN)
        self.status_label.configure(foreground=MUTED)
        target = url if recording and self.source.get() == "Paste URL" else (
            names[0] if len(names) == 1 else f"{len(names)} apps")
        self.append(f"\nStarting {self.mode.get().lower()}: {target}.\n")
        LOGGER.info("Starting operation: %s", args)
        self.refresh()
        threading.Thread(target=self.execute, args=(args,), daemon=True).start()

    def execute(self, args: list[str]) -> None:
        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        try:
            with subprocess.Popen(
                [str(executable), "-B", "-u", "-m", "Backend.cli", *args], cwd=ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ) as process:
                for line in process.stdout:
                    LOGGER.info("CLI: %s", line.rstrip())
                    self.events.put(("output", line))
                self.events.put(("done", process.wait()))
        except Exception as exc:
            LOGGER.exception("Could not start operation")
            self.events.put(("notice", ("Could not start the operation. Open log for the reason.", "error")))
            self.events.put(("done", 1))

    def poll(self) -> None:
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == "output":
                self.track_artifact(value)
                self.warnings |= "Run SUCCESS WITH WARNINGS." in value
                notice = readable_event(value)
                if notice and notice != self.last_event:
                    self.append(notice[0] + "\n", notice[1])
                    self.last_event = notice
            elif kind == "notice":
                self.append(value[0] + "\n", value[1])
            else:
                self.busy = False
                color = "#b07613" if value == 0 and self.warnings else "#168063" if value == 0 else "#c44752"
                self.indicator.stop(color)
                self.status_label.configure(foreground=color)
                self.status.set("Completed with warnings" if value == 0 and self.warnings
                                else "Completed successfully" if value == 0
                                else "Incomplete - review the report and log")
                if value != 0:
                    self.append("Operation incomplete. Review Open report and Open log.\n", "error")
                self.refresh()
        if self.busy:
            minutes, seconds = divmod(int(time.monotonic() - self.started), 60)
            self.status.set(f"{self.mode.get()} in progress  |  {minutes:02d}:{seconds:02d}")
        self.update_links()
        self.window.after(100, self.poll)

    # 5. Open only announced artifacts inside their configured output directories.
    def track_artifact(self, line: str) -> None:
        for kind, marker, directory, suffix in (
            ("recording", "Recording file: ", self.settings.recordings_dir, ".json"),
            ("report", "Excel report: ", self.settings.reports_dir, ".xlsx"),
            ("log", "Log file: ", self.settings.logs_dir, ".log"),
        ):
            if marker in line:
                path = Path(line.split(marker, 1)[1].strip()).resolve()
                if path.parent == directory.resolve() and path.suffix.lower() == suffix:
                    self.artifacts[kind] = path

    def update_links(self) -> None:
        for kind, button in self.artifact_buttons.items():
            path = self.artifacts[kind]
            button.configure(state="normal" if path and path.is_file() else "disabled")

    def open_artifact(self, kind: str) -> None:
        path = self.artifacts[kind]
        if not path or not path.is_file():
            messagebox.showinfo("File unavailable", "This file has not been created yet or has moved.", parent=self.window)
            self.update_links()
            return
        try:
            os.startfile(str(path))
        except OSError as exc:
            messagebox.showerror("Could not open file", str(exc), parent=self.window)

    def close(self) -> None:
        if self.busy:
            messagebox.showinfo("Operation active", "Finish the active operation first. Close the automation Chrome window to finish recording.", parent=self.window)
        else:
            self.indicator.stop()
            self.window.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    try:
        Launcher(window)
    except Exception as exc:
        LOGGER.exception("Could not open launcher")
        messagebox.showerror("Could not open launcher", str(exc), parent=window)
        window.destroy()
    else:
        window.mainloop()
