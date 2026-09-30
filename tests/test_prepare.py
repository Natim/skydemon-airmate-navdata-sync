from __future__ import annotations

import zipfile
from pathlib import Path

from navdata_sync.catalog import Kind, RemoteFile
from navdata_sync.prepare import build, is_ready


def test_prepare_layout_and_missing_files(tmp_path: Path) -> None:
    download_dir = tmp_path / "downloads"
    prepared_dir = tmp_path / "prepared"
    download_dir.mkdir()

    (download_dir / "airmate_av_data_eu_2609_123456.dup").write_bytes(b"nav")
    (download_dir / "CHARTS-123456.key").write_bytes(b"key")
    (download_dir / "VFR-FRANCE.dcf").write_bytes(b"chart")

    zip_path = download_dir / "FR-Plates-2609.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("ChartData/Plates/LFMN.pdf", b"%PDF")

    files = [
        RemoteFile("https://example.test/a.dup", "airmate_av_data_eu_2609_123456.dup", Kind.DATA),
        RemoteFile("https://example.test/obs.dup", "airmate_obstacle_data_eu_2609_123456.dup", Kind.DATA),
        RemoteFile("https://example.test/k.key", "CHARTS-123456.key", Kind.KEY),
        RemoteFile("https://example.test/p.zip", "FR-Plates-2609.zip", Kind.PLATES),
        RemoteFile("https://example.test/r.dcf", "VFR-FRANCE.dcf", Kind.RASTER),
    ]

    missing = build(files, download_dir, prepared_dir)

    assert missing == ["airmate_obstacle_data_eu_2609_123456.dup"]
    assert (prepared_dir / "AIRMATE_AV_DATA_EU_2609_123456.DUP").read_bytes() == b"nav"
    assert (prepared_dir / "CHARTS-123456.key").read_bytes() == b"key"
    assert (prepared_dir / "Raster" / "VFR-FRANCE.dcf").read_bytes() == b"chart"
    assert (prepared_dir / "ChartData" / "Plates" / "LFMN.pdf").read_bytes() == b"%PDF"
    assert not (prepared_dir / ".navdata-stamp").exists()
    assert not is_ready(files, prepared_dir)


def test_is_ready_after_complete_build(tmp_path: Path) -> None:
    download_dir = tmp_path / "downloads"
    prepared_dir = tmp_path / "prepared"
    files = _complete_files(download_dir)

    assert not is_ready(files, prepared_dir)
    assert build(files, download_dir, prepared_dir) == []
    assert is_ready(files, prepared_dir)

    stamp = (prepared_dir / ".navdata-stamp").read_text(encoding="utf-8")
    assert "2609" in stamp
    (prepared_dir / "AIRMATE_AV_DATA_EU_2609_123456.DUP").unlink()
    assert not is_ready(files, prepared_dir)


def test_is_ready_rejects_other_cycle(tmp_path: Path) -> None:
    download_dir = tmp_path / "downloads"
    prepared_dir = tmp_path / "prepared"
    files = _complete_files(download_dir)
    build(files, download_dir, prepared_dir)

    other = [
        RemoteFile(file.url.replace("2609", "2610"), file.name.replace("2609", "2610"), file.kind)
        if "2609" in file.name
        else file
        for file in files
    ]
    assert not is_ready(other, prepared_dir)


def _complete_files(download_dir: Path) -> list[RemoteFile]:
    download_dir.mkdir()
    (download_dir / "airmate_av_data_eu_2609_123456.dup").write_bytes(b"nav")
    (download_dir / "airmate_obstacle_data_eu_2609_123456.dup").write_bytes(b"obs")
    (download_dir / "CHARTS-123456.key").write_bytes(b"key")
    (download_dir / "VFR-FRANCE.dcf").write_bytes(b"chart")
    with zipfile.ZipFile(download_dir / "FR-Plates-2609.zip", "w") as archive:
        archive.writestr("ChartData/Plates/LFMN.pdf", b"%PDF")
    return [
        RemoteFile("https://example.test/a.dup", "airmate_av_data_eu_2609_123456.dup", Kind.DATA),
        RemoteFile("https://example.test/obs.dup", "airmate_obstacle_data_eu_2609_123456.dup", Kind.DATA),
        RemoteFile("https://example.test/k.key", "CHARTS-123456.key", Kind.KEY),
        RemoteFile("https://example.test/p.zip", "FR-Plates-2609.zip", Kind.PLATES),
        RemoteFile("https://example.test/r.dcf", "VFR-FRANCE.dcf", Kind.RASTER),
    ]
