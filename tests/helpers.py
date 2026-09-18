"""Shared helpers. Isolated from the developer's real config and env."""

from __future__ import annotations

from pathlib import Path

CONFIG_TOML = """\
[airmate]
id = "TESTID"
serial = "123456"
base_url = "https://example.test/navdata"

[data]
cycle = "2609"
plates = ["FR"]
raster = ["VFR-FRANCE.dcf"]

[paths]
download_dir = "downloads"
prepared_dir = "prepared"
{usb}
"""


def write_config(tmp_path: Path, usb: str = "") -> Path:
    path = tmp_path / "config.toml"
    path.write_text(CONFIG_TOML.format(usb=usb), encoding="utf-8")
    return path
