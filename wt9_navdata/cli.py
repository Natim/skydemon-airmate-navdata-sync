"""Command line entry point: download, stage, optionally sync."""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
from pathlib import Path

from . import catalog, download, prepare
from .config import DEFAULT_CONFIG, ConfigError
from .config import load as load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="navdata-update",
        description="Download an Airmate AIRAC cycle and lay it out for a "
        "Dynon SkyView USB stick.",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        metavar="PATH",
        help=f"configuration file (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--cycle",
        metavar="YYCC",
        help="override data.cycle for this run, e.g. 2609",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list the files the configuration resolves to and exit",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="rebuild the staging folder from the download cache only",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="run rsync to paths.usb_target instead of just printing it",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"❌ {exc}")
        return 2

    if args.cycle:
        config = dataclasses.replace(config, cycle=args.cycle)

    # Checked before anything is downloaded or staged, since --sync is the whole
    # point of the run when it is passed.
    if args.sync and config.usb_target is None:
        print("❌ --sync demande paths.usb_target dans la configuration")
        return 2

    files = catalog.build(config)

    if args.list:
        for file in files:
            print(f"{file.kind.value:>7}  {file.name}")
        print(f"\ncycle {config.cycle} · {len(files)} fichiers · {config.download_dir}")
        return 0

    if not args.skip_download:
        asyncio.run(download.run(files, config.download_dir))

    missing = prepare.build(files, config.download_dir, config.prepared_dir)

    if args.sync and config.usb_target is not None:
        if missing:
            print("❌ Synchronisation annulée: des fichiers manquent")
            return 1
        return prepare.sync(config.prepared_dir, config.usb_target)

    print(prepare.describe_sync(config.prepared_dir, config.usb_target))
    return 1 if missing else 0
