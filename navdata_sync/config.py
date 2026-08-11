"""Loading and validation of config.toml.

Everything that identifies a particular subscription or machine lives in the
config file, never in the code: the Airmate customer id, the Dynon serial, the
AIRAC cycle and the local paths. See config.example.toml for the reference.
"""
from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "navdata-sync"
PACKAGE_DIR = Path(__file__).resolve().parent
CHECKOUT_ROOT = PACKAGE_DIR.parent  # the repository root, in a git checkout

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


def user_config() -> Path:
    """The per-user configuration, following the XDG base directory spec."""
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP_NAME / "config.toml"


def search_path() -> list[Path]:
    """Where an invocation without --config looks, in order.

    The current directory comes first so a checkout keeps working as a
    self-contained folder, then the per-user location for an installed copy,
    then the checkout root so cron jobs and shell aliases need no --config.
    """
    candidates = [Path.cwd() / "config.toml", user_config()]

    # Only a checkout has a sibling pyproject.toml; for an installed package
    # CHECKOUT_ROOT is site-packages, which would be nonsense to suggest.
    if (CHECKOUT_ROOT / "pyproject.toml").is_file():
        candidates.append(CHECKOUT_ROOT / "config.toml")

    return list(dict.fromkeys(candidates))


def example_config() -> Path | None:
    """The bundled template: beside the package, or inside it once installed."""
    for candidate in (
        CHECKOUT_ROOT / "config.example.toml",
        PACKAGE_DIR / "config.example.toml",
    ):
        if candidate.is_file():
            return candidate
    return None


def init_config(target: Path | None = None) -> Path:
    """Copy the bundled template to target, without ever clobbering a config."""
    target = (target or user_config()).expanduser()
    if target.exists():
        raise ConfigError(f"{target} already exists, leaving it alone")

    example = example_config()
    if example is None:
        raise ConfigError("this installation is missing its config.example.toml")

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(example, target)
    return target


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
    """Read a config file, apply environment overrides and validate it.

    Without an explicit path, the first file in search_path() wins.
    """
    if path is None:
        searched = search_path()
        path = next((candidate for candidate in searched if candidate.is_file()), None)
        if path is None:
            locations = "".join(f"      {candidate}\n" for candidate in searched)
            raise ConfigError(
                "no configuration file found, looked in:\n" + locations
                + "    create one with: navdata-update --init-config"
            )

    path = path.expanduser()
    if not path.is_file():
        raise ConfigError(f"no config file at {path}")

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
