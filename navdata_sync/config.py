"""Loading and validation of config.toml.

Everything that identifies a particular subscription or machine lives in the
config file, never in the code: the Airmate customer id, the Dynon serial, the
AIRAC cycle and the local paths. See config.example.toml for the reference.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "config.toml"
EXAMPLE_CONFIG = REPO_ROOT / "config.example.toml"

ID_ENV = "AIRMATE_ID"
SERIAL_ENV = "AIRMATE_SERIAL"

# Values shipped in config.example.toml. Refusing them keeps a half-filled copy
# of the example from producing a run of 404s.
PLACEHOLDERS = frozenset({
    "YOUR_AIRMATE_ID",
    "000000",
    "/run/media/YOUR_USER/LH D1000",
})


class ConfigError(Exception):
    """Raised when the config file is missing, unreadable or incomplete."""


@dataclass(frozen=True)
class Config:
    airmate_id: str
    serial: str
    base_url: str
    cycle: str
    plates: tuple[str, ...]
    raster: tuple[str, ...]
    download_dir: Path
    prepared_dir: Path
    usb_target: Path | None


def load(path: Path | None = None) -> Config:
    """Read a config file, apply environment overrides and validate it."""
    path = (path or DEFAULT_CONFIG).expanduser()

    if not path.is_file():
        raise ConfigError(
            f"no config file at {path}\n"
            f"    create one with: cp {_display(EXAMPLE_CONFIG)} "
            f"{_display(path)}"
        )

    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    airmate = _section(raw, path, "airmate")
    data = _section(raw, path, "data")
    paths = _section(raw, path, "paths")

    # The environment wins so the two identifying values can be kept in a
    # password manager or a shell profile instead of on disk.
    airmate_id = os.environ.get(ID_ENV) or _string(airmate, path, "airmate", "id")
    serial = os.environ.get(SERIAL_ENV) or _string(airmate, path, "airmate", "serial")

    for name, value, env in (("id", airmate_id, ID_ENV), ("serial", serial, SERIAL_ENV)):
        if value in PLACEHOLDERS:
            raise ConfigError(
                f"airmate.{name} is still the example placeholder {value!r}; "
                f"set it in {path} or export {env}"
            )

    # Relative paths follow the config file, so the script behaves the same from
    # any working directory (cron, a shell alias, the repo itself).
    anchor = path.parent

    usb_target = paths.get("usb_target") or None
    if usb_target in PLACEHOLDERS:
        usb_target = None

    return Config(
        airmate_id=airmate_id,
        serial=serial,
        base_url=_string(airmate, path, "airmate", "base_url").rstrip("/"),
        cycle=_string(data, path, "data", "cycle"),
        plates=_string_list(data, path, "data", "plates"),
        raster=_string_list(data, path, "data", "raster"),
        download_dir=_path(paths, path, "paths", "download_dir", anchor),
        prepared_dir=_path(paths, path, "paths", "prepared_dir", anchor),
        usb_target=Path(usb_target).expanduser() if usb_target else None,
    )


def _section(raw: dict, path: Path, name: str) -> dict:
    section = raw.get(name)
    if not isinstance(section, dict):
        raise ConfigError(f"{path} has no [{name}] section")
    return section


def _string(section: dict, path: Path, name: str, key: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{path} is missing a non-empty {name}.{key}")
    return value


def _string_list(section: dict, path: Path, name: str, key: str) -> tuple[str, ...]:
    value = section.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{name}.{key} in {path} must be a list of strings")
    return tuple(value)


def _path(section: dict, path: Path, name: str, key: str, anchor: Path) -> Path:
    value = Path(_string(section, path, name, key)).expanduser()
    return value if value.is_absolute() else anchor / value


def _display(path: Path) -> str:
    """Shorten a path to a repo-relative one when it helps readability."""
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)
