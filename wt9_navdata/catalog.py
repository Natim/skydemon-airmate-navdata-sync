"""Turns a Config into the list of files to fetch from Airmate.

Airmate publishes three kinds of URL:

  <base>/<customer id>/...   subscription-bound data, one file per serial
  <base>/Plates/...          approach plate bundles, one zip per region
  <base>/Raster/...          raster VFR charts, shared by everyone
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .config import Config


class Kind(Enum):
    """What a file becomes on the USB stick, which decides how it is staged."""

    DATA = "data"      # .dup, navdata and obstacles, uppercased at the root
    KEY = "key"        # CHARTS-<serial>.key, unlocks the raster layers
    PLATES = "plates"  # zip expanded at the root, creates ChartData/
    RASTER = "raster"  # .dcf copied under Raster/


@dataclass(frozen=True)
class RemoteFile:
    url: str
    name: str
    kind: Kind

    @property
    def always_refresh(self) -> bool:
        """Whether a byte-identical local copy still has to be re-downloaded.

        The key file changes content every AIRAC cycle (chart filenames and auth
        codes rotate) while keeping the exact same byte size, so a size-only
        "already complete" check would keep a stale key on disk. The Dynon then
        silently hides every layer whose filename or code no longer matches.
        """
        return self.kind is Kind.KEY


def build(config: Config) -> list[RemoteFile]:
    account = f"{config.base_url}/{config.airmate_id}"
    files = [
        RemoteFile(
            f"{account}/airmate_av_data_eu_{config.cycle}_{config.serial}.dup",
            f"airmate_av_data_eu_{config.cycle}_{config.serial}.dup",
            Kind.DATA,
        ),
        RemoteFile(
            f"{account}/airmate_obstacle_data_eu_{config.cycle}_{config.serial}.dup",
            f"airmate_obstacle_data_eu_{config.cycle}_{config.serial}.dup",
            Kind.DATA,
        ),
        RemoteFile(
            f"{account}/CHARTS-{config.serial}.key",
            f"CHARTS-{config.serial}.key",
            Kind.KEY,
        ),
    ]

    for region in config.plates:
        name = f"{region}-Plates-{config.cycle}.zip"
        files.append(RemoteFile(f"{config.base_url}/Plates/{name}", name, Kind.PLATES))

    for name in config.raster:
        files.append(RemoteFile(f"{config.base_url}/Raster/{name}", name, Kind.RASTER))

    return files
