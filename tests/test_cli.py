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


def test_sync_reuses_existing_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from navdata_sync.catalog import Kind, RemoteFile
    from navdata_sync.prepare import build

    usb = tmp_path / "RH D1000"
    usb.mkdir()
    path = write_config(tmp_path, f'usb_targets = ["{usb.as_posix()}"]')
    download_dir = tmp_path / "downloads"
    prepared_dir = tmp_path / "prepared"
    download_dir.mkdir()
    (download_dir / "airmate_av_data_eu_2609_123456.dup").write_bytes(b"nav")
    (download_dir / "airmate_obstacle_data_eu_2609_123456.dup").write_bytes(b"obs")
    (download_dir / "CHARTS-123456.key").write_bytes(b"key")
    (download_dir / "VFR-FRANCE.dcf").write_bytes(b"chart")
    import zipfile

    with zipfile.ZipFile(download_dir / "FR-Plates-2609.zip", "w") as archive:
        archive.writestr("ChartData/Plates/LFMN.pdf", b"%PDF")

    files = [
        RemoteFile("https://example.test/a.dup", "airmate_av_data_eu_2609_123456.dup", Kind.DATA),
        RemoteFile("https://example.test/obs.dup", "airmate_obstacle_data_eu_2609_123456.dup", Kind.DATA),
        RemoteFile("https://example.test/k.key", "CHARTS-123456.key", Kind.KEY),
        RemoteFile("https://example.test/p.zip", "FR-Plates-2609.zip", Kind.PLATES),
        RemoteFile("https://example.test/r.dcf", "VFR-FRANCE.dcf", Kind.RASTER),
    ]
    assert build(files, download_dir, prepared_dir) == []

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("download/prepare should be skipped")

    monkeypatch.setattr("navdata_sync.cli.download.run", boom)
    monkeypatch.setattr("navdata_sync.cli.prepare.build", boom)
    monkeypatch.setattr("navdata_sync.usb.os.sync", lambda: None)

    assert main(["--config", str(path), "--sync"]) == 0
    out = capsys.readouterr().out
    assert "préparation ignorée" in out
    assert (usb / "CHARTS-123456.key").read_bytes() == b"key"


def test_skip_prepare_without_staging(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_config(tmp_path)
    assert main(["--config", str(path), "--skip-prepare"]) == 1
    assert "skip-prepare" in capsys.readouterr().out
