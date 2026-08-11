#!/usr/bin/env python3
"""Convert a standard MBTiles file into an Airmate-style .dcf.

The Dynon/Airmate .dcf format is just an MBTiles SQLite database
(tiles + metadata tables) with PNG tiles and a set of Airmate-specific
metadata keys. To be *displayed*, a raster layer must also have a matching
entry in CHARTS-<serial>.key; this script does NOT create key entries.

Two modes:

  * --template PATH  : clone the metadata table verbatim from an existing
    official .dcf (recommended when reusing an owned key slot: it maximises
    the chance of passing the authenticator if that check is metadata-bound).

  * --meta k=v ...   : set individual metadata keys (standalone chart).

Tiles are re-encoded to PNG by default so the declared `format=png` stays
truthful; pass --keep-format to copy tile bytes as-is.
"""
import argparse
import io
import shutil
import sqlite3
import sys
from pathlib import Path


def reencode_png(blob: bytes) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(blob)) as im:
        out = io.BytesIO()
        im.convert("RGB").save(out, format="PNG", optimize=True)
        return out.getvalue()


def build(source: Path, output: Path, template: Path | None,
          meta: dict[str, str], to_png: bool) -> None:
    if template:
        shutil.copyfile(template, output)
        dst = sqlite3.connect(output)
        dst.execute("DELETE FROM tiles")
    else:
        if output.exists():
            output.unlink()
        dst = sqlite3.connect(output)
        dst.execute(
            "CREATE TABLE metadata (name text NOT NULL, value text NOT NULL)"
        )
        dst.execute(
            "CREATE TABLE tiles (zoom_level integer NOT NULL,"
            "tile_column integer NOT NULL, tile_row integer NOT NULL,"
            "tile_data blob NOT NULL,"
            "UNIQUE (zoom_level, tile_column, tile_row))"
        )

    if meta:
        for k, v in meta.items():
            dst.execute("DELETE FROM metadata WHERE name=?", (k,))
            dst.execute(
                "INSERT INTO metadata (name, value) VALUES (?, ?)", (k, v)
            )
    if to_png:
        dst.execute("DELETE FROM metadata WHERE name='format'")
        dst.execute("INSERT INTO metadata (name, value) VALUES ('format','png')")

    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    total = src.execute("SELECT count(*) FROM tiles").fetchone()[0]
    done = 0
    rows = src.execute(
        "SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles"
    )
    for z, x, y, data in rows:
        if data is not None and to_png:
            data = reencode_png(data)
        dst.execute(
            "INSERT OR REPLACE INTO tiles VALUES (?,?,?,?)", (z, x, y, data)
        )
        done += 1
        if done % 500 == 0 or done == total:
            print(f"  tiles {done}/{total}", end="\r", flush=True)
    print()
    src.close()
    dst.commit()
    dst.execute("VACUUM")
    dst.commit()
    dst.close()

    size = output.stat().st_size
    print(f"OK -> {output} ({size/1_048_576:.1f} MB, {total} tiles)")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", type=Path, help="input .mbtiles")
    p.add_argument("output", type=Path, help="output .dcf")
    p.add_argument("--template", type=Path,
                   help="official .dcf whose metadata is cloned verbatim")
    p.add_argument("--meta", nargs="*", default=[],
                   help="metadata overrides key=value")
    p.add_argument("--keep-format", action="store_true",
                   help="copy tile bytes as-is instead of re-encoding to PNG")
    args = p.parse_args()

    if not args.source.is_file():
        print(f"source not found: {args.source}", file=sys.stderr)
        return 1
    if args.template and not args.template.is_file():
        print(f"template not found: {args.template}", file=sys.stderr)
        return 1

    meta = {}
    for item in args.meta:
        if "=" not in item:
            print(f"bad --meta entry (need key=value): {item}", file=sys.stderr)
            return 1
        k, v = item.split("=", 1)
        meta[k] = v

    build(args.source, args.output, args.template, meta, not args.keep_format)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
