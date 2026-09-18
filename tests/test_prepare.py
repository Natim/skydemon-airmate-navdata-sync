from __future__ import annotations

import zipfile
from pathlib import Path

from navdata_sync.catalog import Kind, RemoteFile
from navdata_sync.prepare import build


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
