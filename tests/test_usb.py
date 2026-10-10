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


def test_prune_keeps_case_variants(tmp_path: Path) -> None:
    stick = tmp_path / "RH D1000"
    stick.mkdir()
    (stick / "CHARTS.key").write_text("ok", encoding="utf-8")
    (stick / "stale.txt").write_text("x", encoding="utf-8")

    extras = usb.prune_extras(stick, {Path("charts.key")})
    assert extras == [Path("stale.txt")]
    assert (stick / "CHARTS.key").is_file()
    assert not (stick / "stale.txt").exists()


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


def test_prune_reports_scan_and_purge(tmp_path: Path) -> None:
    stick = tmp_path / "RH D1000"
    (stick / "keep.txt").parent.mkdir()
    (stick / "keep.txt").write_text("ok", encoding="utf-8")
    (stick / "old").mkdir()
    (stick / "old" / "nested.bin").write_bytes(b"stale")

    scanned: list[tuple[int, Path]] = []
    purged: list[tuple[int, int, Path]] = []
    extras = usb.prune_extras(
        stick,
        {Path("keep.txt")},
        on_scan=lambda n, rel: scanned.append((n, rel)),
        on_purge=lambda done, total, rel: purged.append((done, total, rel)),
    )

    assert [n for n, _rel in scanned] == list(range(1, len(scanned) + 1))
    assert {rel for _n, rel in scanned} == {Path("keep.txt"), Path("old/nested.bin")}
    assert extras == [Path("old/nested.bin")]
    assert purged[0][2] == Path("old/nested.bin")
    assert purged[-1][0] == purged[-1][1]
    assert Path("old") in [rel for _done, _total, rel in purged]
    assert not (stick / "old").exists()


def test_format_duration() -> None:
    assert usb._format_duration(0) == "0 s"
    assert usb._format_duration(59.4) == "59 s"
    assert usb._format_duration(61) == "1 min 1 s"
    assert usb._format_duration(3661) == "1 h 1 min 1 s"


def test_sync_summary_includes_total_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(usb.os, "sync", lambda: None)
    src = tmp_path / "prepared"
    stick = tmp_path / "LH D1000"
    src.mkdir()
    (src / "a.txt").write_text("a", encoding="utf-8")
    stick.mkdir()

    assert usb.sync(src, (stick,)) == 0
    assert "Durée totale" in capsys.readouterr().out


def test_describe_sync_reports_mount_status(tmp_path: Path) -> None:
    mounted = tmp_path / "RH D1000"
    mounted.mkdir()
    missing = tmp_path / "LH D1000"
    text = usb.describe_sync(tmp_path / "prepared", (mounted, missing))
    assert "montée" in text
    assert "absente" in text
