from __future__ import annotations

from pathlib import Path

import pytest

from navdata_sync import usb


def test_prune_and_relative_files(tmp_path: Path) -> None:
    stick = tmp_path / "RH D1000"
    (stick / "keep.txt").parent.mkdir()
    (stick / "keep.txt").write_text("ok", encoding="utf-8")
    (stick / "old" / "nested.bin").parent.mkdir()
    (stick / "old" / "nested.bin").write_bytes(b"stale")
    (stick / "gone.txt").write_text("x", encoding="utf-8")

    extras = usb.prune_extras(stick, {Path("keep.txt")})
    assert Path("gone.txt") in extras
    assert Path("old/nested.bin") in extras
    assert (stick / "keep.txt").is_file()
    assert not (stick / "gone.txt").exists()
    assert not (stick / "old").exists()


def test_sync_two_targets_copy_skip_rewrite_and_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(usb.os, "sync", lambda: None)

    src = tmp_path / "prepared"
    lh = tmp_path / "LH D1000"
    rh = tmp_path / "RH D1000"
    missing = tmp_path / "not-mounted"
    (src / "Raster").mkdir(parents=True)
    (src / "AIRMATE.DUP").write_bytes(b"navdata" * 1000)
    (src / "CHARTS.key").write_bytes(b"KEY-CYCLE-1")
    (src / "Raster" / "VFR.dcf").write_bytes(b"x" * 4096)
    lh.mkdir()
    rh.mkdir()
    (lh / "stale.txt").write_text("gone", encoding="utf-8")

    assert usb.sync(src, (lh, rh, missing)) == 1
    for stick in (lh, rh):
        assert (stick / "AIRMATE.DUP").read_bytes() == (src / "AIRMATE.DUP").read_bytes()
        assert (stick / "CHARTS.key").read_bytes() == b"KEY-CYCLE-1"
        assert (stick / "Raster" / "VFR.dcf").read_bytes() == b"x" * 4096
    assert not (lh / "stale.txt").exists()

    assert usb.sync(src, (lh, rh)) == 0

    (src / "CHARTS.key").write_bytes(b"KEY-CYCLE-2")
    assert usb.sync(src, (lh, rh)) == 0
    assert (lh / "CHARTS.key").read_bytes() == b"KEY-CYCLE-2"
    assert (rh / "CHARTS.key").read_bytes() == b"KEY-CYCLE-2"

    (src / "Raster" / "VFR.dcf").unlink()
    assert usb.sync(src, (lh,)) == 0
    assert not (lh / "Raster" / "VFR.dcf").exists()


def test_describe_sync_reports_mount_status(tmp_path: Path) -> None:
    mounted = tmp_path / "RH D1000"
    mounted.mkdir()
    missing = tmp_path / "LH D1000"
    text = usb.describe_sync(tmp_path / "prepared", (mounted, missing))
    assert "montée" in text
    assert "absente" in text
