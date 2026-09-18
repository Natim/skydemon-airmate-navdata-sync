from __future__ import annotations

from pathlib import Path

from navdata_sync.catalog import build, Kind
from navdata_sync.config import load
from tests.helpers import write_config


def test_catalog_urls_and_key_always_refresh(tmp_path: Path) -> None:
    config = load(write_config(tmp_path))
    files = {file.name: file for file in build(config)}

    data = files["airmate_av_data_eu_2609_123456.dup"]
    assert data.kind is Kind.DATA
    assert data.url.endswith("/TESTID/airmate_av_data_eu_2609_123456.dup")
    assert not data.always_refresh

    key = files["CHARTS-123456.key"]
    assert key.kind is Kind.KEY
    assert key.always_refresh

    plates = files["FR-Plates-2609.zip"]
    assert plates.kind is Kind.PLATES
    assert plates.url.endswith("/Plates/FR-Plates-2609.zip")

    raster = files["VFR-FRANCE.dcf"]
    assert raster.kind is Kind.RASTER
    assert raster.url.endswith("/Raster/VFR-FRANCE.dcf")
