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

__all__ = ["build", "describe_sync", "is_ready", "sync"]

# Left in the staging folder so a later --sync can reuse it. Hidden so it is
# not copied onto the USB stick.
STAMP_NAME = ".navdata-stamp"


def is_ready(files: list[RemoteFile], prepared_dir: Path) -> bool:
    """Whether prepared_dir already matches this catalog and can be reused."""
    if not prepared_dir.is_dir():
        return False
    stamp = prepared_dir / STAMP_NAME
    if stamp.is_file() and stamp.read_text(encoding="utf-8") != _stamp_payload(files):
        return False
    return all(path.exists() for path in _expected_outputs(files, prepared_dir))


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

    if not missing:
        (prepared_dir / STAMP_NAME).write_text(_stamp_payload(files), encoding="utf-8")

    return missing


def _stamp_payload(files: list[RemoteFile]) -> str:
    return "\n".join(f"{file.kind.value}\t{file.name}" for file in sorted(files, key=lambda f: f.name))


def _expected_outputs(files: list[RemoteFile], prepared_dir: Path) -> list[Path]:
    paths: list[Path] = []
    needs_plates = False
    for file in files:
        match file.kind:
            case Kind.DATA:
                paths.append(prepared_dir / file.name.upper())
            case Kind.KEY:
                paths.append(prepared_dir / file.name)
            case Kind.PLATES:
                needs_plates = True
            case Kind.RASTER:
                paths.append(prepared_dir / "Raster" / file.name)
    if needs_plates:
        paths.append(prepared_dir / "ChartData")
    return paths
