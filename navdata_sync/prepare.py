"""Staging of the downloaded files into the layout the Dynon expects.

The root of the USB stick looks like this:

    AIRMATE_AV_DATA_EU_<cycle>_<serial>.DUP
    AIRMATE_OBSTACLE_DATA_EU_<cycle>_<serial>.DUP
    CHARTS-<serial>.key
    ChartData/Plates/...
    Raster/VFR-*.dcf
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from .catalog import Kind, RemoteFile
from .usb import describe_sync, sync

__all__ = ["build", "describe_sync", "sync"]


def build(files: list[RemoteFile], download_dir: Path, prepared_dir: Path) -> list[str]:
    """Lay the downloads out under prepared_dir. Returns the names left out."""
    print("📦 Construction du dossier final...")

    if prepared_dir.exists():
        shutil.rmtree(prepared_dir)
    prepared_dir.mkdir(parents=True)

    missing = []
    for file in sorted(files, key=lambda f: f.name):
        source = download_dir / file.name
        if not source.is_file():
            missing.append(file.name)
            continue

        match file.kind:
            case Kind.DATA:
                shutil.copyfile(source, prepared_dir / file.name.upper())
            case Kind.KEY:
                shutil.copyfile(source, prepared_dir / file.name)
            case Kind.PLATES:
                print(f"📂 Extraction {file.name}")
                with zipfile.ZipFile(source) as archive:
                    archive.extractall(prepared_dir)
            case Kind.RASTER:
                raster_dir = prepared_dir / "Raster"
                raster_dir.mkdir(exist_ok=True)
                shutil.copyfile(source, raster_dir / file.name)

    for name in missing:
        print(f"⚠️  {name} absent du dossier de téléchargement, ignoré")

    return missing
