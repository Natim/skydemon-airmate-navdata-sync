"""Staging of the downloaded files into the layout the Dynon expects.

The root of the USB stick looks like this:

    AIRMATE_AV_DATA_EU_<cycle>_<serial>.DUP
    AIRMATE_OBSTACLE_DATA_EU_<cycle>_<serial>.DUP
    CHARTS-<serial>.key
    ChartData/Plates/...
    Raster/VFR-*.dcf
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
import zipfile
from pathlib import Path

from .catalog import Kind, RemoteFile

# The staging folder is rebuilt from scratch on every run, so every file gets a
# fresh mtime and rsync's default size+mtime check would recopy everything:
#   --checksum          decide by content, not the (always-new) timestamp, so
#                       only files whose bytes actually changed get written
#                       (--size-only would miss same-size changes like the key)
#   --inplace           write into the destination file directly, no temp copy,
#                       which matters on a nearly-full FAT-32 stick
#   --no-whole-file     use the delta algorithm even for a local/USB target so
#                       only the changed blocks are rewritten
#   --no-inc-recursive  build the full file list up front for an accurate
#                       --info=progress2 percentage
RSYNC_FLAGS = (
    "-avh",
    "--checksum",
    "--inplace",
    "--no-whole-file",
    "--no-inc-recursive",
    "--info=progress2",
    "--delete",
)


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


def rsync_command(prepared_dir: Path, usb_target: Path) -> list[str]:
    # The trailing slash on the source copies its *contents*, not the folder.
    return ["rsync", *RSYNC_FLAGS, f"{prepared_dir}/", f"{usb_target}/"]


def describe_sync(prepared_dir: Path, usb_target: Path | None) -> str:
    if usb_target is None:
        return (
            f"✅ Dossier prêt: {prepared_dir}\n"
            "   Renseignez paths.usb_target dans config.toml pour la synchronisation."
        )
    command = shlex.join(rsync_command(prepared_dir, usb_target))
    return f"✅ Dossier prêt pour rsync:\n   {command}"


def sync(prepared_dir: Path, usb_target: Path) -> int:
    """Copy the staging folder onto the USB stick. Returns the rsync exit code."""
    if not usb_target.is_dir():
        # Without this check rsync would happily create the mount point as a
        # plain directory and fill up the system disk instead.
        print(f"❌ {usb_target} introuvable: la clé USB est-elle montée ?")
        return 1

    command = rsync_command(prepared_dir, usb_target)
    print(f"🔄 {shlex.join(command)}")
    return subprocess.run(command).returncode
