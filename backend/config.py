"""Central configuration, app inventory, and logging setup."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


# 1. Time and artifact names.
LEBANON_TIMEZONE = ZoneInfo("Asia/Beirut")


def lebanon_now() -> datetime:
    return datetime.now(LEBANON_TIMEZONE)


class _LebanonFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        timestamp = datetime.fromtimestamp(record.created, LEBANON_TIMEZONE)
        return (
            timestamp.strftime(datefmt)
            if datefmt
            else timestamp.isoformat(timespec="seconds")
        )


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = PROJECT_ROOT / "Artifacts"
APPS_FILE = "Apps.json"
APP_GROUPS = ("plus", "core")
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def artifact_path(directory: Path, label: str, suffix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{label}  -  {lebanon_now():%m-%d__%H.%M}"
    path, number = directory / f"{stem}{suffix}", 2
    while path.exists():
        path = directory / f"{stem} ({number}){suffix}"
        number += 1
    return path


# 2. Environment and configuration.
def _load_local_env(path: Path = PROJECT_ROOT / ".env") -> None:
    """Load simple KEY=VALUE settings without overriding process variables."""
    if not path.is_file():
        return

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"Invalid .env entry on line {line_number}")

        key, value = (part.strip() for part in line.split("=", 1))
        if not _ENV_KEY.fullmatch(key):
            raise ValueError(f"Invalid .env key on line {line_number}: {key!r}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true/false, yes/no, on/off, or 1/0")


def _env_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _env_path(name: str, default: str) -> Path:
    path = Path(os.getenv(name, default)).expanduser()
    path = path if path.is_absolute() else PROJECT_ROOT / path
    # Preserve former default-path overrides after relocating the output folders.
    previous = {
        "LOGS_DIR": "logs",
        "REPORTS_DIR": "reports",
        "INSPECTIONS_DIR": "inspections",
        "SCREENSHOTS_DIR": "backend/screenshots",
    }
    if name in previous and path.resolve() == PROJECT_ROOT / previous[name]:
        return ARTIFACTS_DIR / ("screenshots" if name == "SCREENSHOTS_DIR" else previous[name])
    return path


def resolve_apps_inventory(
    path: Path, group: str | None = None, *, default_group: str = APP_GROUPS[0]
) -> tuple[Path, str]:
    """Resolve inventory selection, preserving the former built-in file arguments."""
    path = path.resolve()
    for previous_group in APP_GROUPS:
        if path == PROJECT_ROOT / f"{previous_group}_apps.json":
            path = PROJECT_ROOT / APPS_FILE
            if group is None:
                group = previous_group
            break
    group = default_group if group is None else group
    if group not in APP_GROUPS:
        raise ValueError(f"Choose an app group: {' or '.join(APP_GROUPS)}.")
    return path, group


def _validate_airtable_url(url: str, source: str) -> str:
    normalized = url.strip()
    parsed = urlparse(normalized)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or (hostname != "airtable.com" and not hostname.endswith(".airtable.com"))
    ):
        raise ValueError(f"{source} must be an https://airtable.com URL")
    return normalized


@dataclass(frozen=True, slots=True)
class AppConfig:
    """One named Airtable app target from an inventory."""

    name: str
    url: str


@dataclass(frozen=True, slots=True)
class Settings:
    """Environment-level runtime settings."""

    apps_file: Path
    chrome_profile_dir: Path
    screenshots_dir: Path
    inspections_dir: Path
    reports_dir: Path
    browser_timeout_ms: int
    navigation_timeout_ms: int
    concurrency: int
    headless: bool
    slow_mo_ms: int
    logs_dir: Path = ARTIFACTS_DIR / "logs"
    apps_group: str = APP_GROUPS[0]

    @classmethod
    def from_env(cls) -> "Settings":
        _load_local_env()
        apps_file, apps_group = resolve_apps_inventory(
            _env_path("APPS_FILE", APPS_FILE), os.getenv("APPS_GROUP")
        )
        settings = cls(
            apps_file=apps_file,
            apps_group=apps_group,
            chrome_profile_dir=_env_path("CHROME_PROFILE_DIR", "chrome-profile"),
            screenshots_dir=_env_path("SCREENSHOTS_DIR", "Artifacts/screenshots"),
            inspections_dir=_env_path("INSPECTIONS_DIR", "Artifacts/inspections"),
            reports_dir=_env_path("REPORTS_DIR", "Artifacts/reports"),
            logs_dir=_env_path("LOGS_DIR", "Artifacts/logs"),
            browser_timeout_ms=_env_positive_int("BROWSER_TIMEOUT_MS", 15_000),
            navigation_timeout_ms=_env_positive_int(
                "NAVIGATION_TIMEOUT_MS", 45_000
            ),
            concurrency=_env_positive_int("CONCURRENCY", 3),
            headless=_env_bool("HEADLESS", False),
            slow_mo_ms=int(os.getenv("SLOW_MO_MS", "0")),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.slow_mo_ms < 0:
            raise ValueError("SLOW_MO_MS cannot be negative")

    def ensure_runtime_dirs(self) -> None:
        for directory in (
            self.chrome_profile_dir,
            self.screenshots_dir,
            self.inspections_dir,
            self.reports_dir,
            self.logs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


# 3. Inventory validation.
def load_apps(path: Path, group: str | None = None) -> tuple[AppConfig, ...]:
    """Load one inventory group, also accepting existing standalone array files."""
    path, group = resolve_apps_inventory(path, group)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"App inventory not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    source = path.name
    if isinstance(raw, dict):
        source = f"{path.name} group {group!r}"
        if group not in raw:
            raise ValueError(f"{path.name} is missing app group {group!r}")
        raw = raw[group]
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{source} must contain a non-empty JSON array")

    apps: list[AppConfig] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{source} item {index} must be an object")
        name = item.get("name")
        url = item.get("url")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{source} item {index} needs a non-empty name")
        if not isinstance(url, str):
            raise ValueError(f"{source} item {index} needs a URL string")
        apps.append(
            AppConfig(
                name=name.strip(),
                url=_validate_airtable_url(url, f"{source} item {index} URL"),
            )
        )

    names = [app.name.casefold() for app in apps]
    urls = [app.url for app in apps]
    if len(names) != len(set(names)):
        raise ValueError(f"{source} contains duplicate app names")
    if len(urls) != len(set(urls)):
        raise ValueError(f"{source} contains duplicate URLs")
    return tuple(apps)


# 4. Local diagnostics and console output.
def configure_logging(settings: Settings, *, verbose: bool = False, label: str = "session") -> Path:
    """Save each operation's diagnostics while streaming them to the launcher."""
    settings.ensure_runtime_dirs()
    level = logging.DEBUG if verbose else logging.INFO
    formatter = _LebanonFormatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()

    path = artifact_path(settings.logs_dir, re.sub(r"[^\w-]+", "-", label).strip("-") or "session", ".log")
    handlers = [logging.FileHandler(path, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.insert(0, logging.StreamHandler())
    for handler in handlers:
        handler.setLevel(level)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.info("Log file: %s", path)
    return path
