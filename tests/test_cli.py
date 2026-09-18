from __future__ import annotations

from pathlib import Path

import pytest

from navdata_sync.cli import main
from tests.helpers import write_config


def test_list_prints_catalog(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_config(tmp_path)
    assert main(["--config", str(path), "--list"]) == 0
    out = capsys.readouterr().out
    assert "CHARTS-123456.key" in out
    assert "cycle 2609" in out


def test_cycle_override(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_config(tmp_path)
    assert main(["--config", str(path), "--list", "--cycle", "2610"]) == 0
    out = capsys.readouterr().out
    assert "FR-Plates-2610.zip" in out
    assert "cycle 2610" in out


def test_sync_without_usb_targets(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_config(tmp_path)
    assert main(["--config", str(path), "--sync"]) == 2
    assert "usb_target" in capsys.readouterr().out


def test_init_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "new.toml"
    assert main(["--init-config", "--config", str(target)]) == 0
    assert target.is_file()
    assert "YOUR_AIRMATE_ID" in target.read_text(encoding="utf-8")
    assert main(["--init-config", "--config", str(target)]) == 2
