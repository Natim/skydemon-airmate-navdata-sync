# skydemon-airmate-navdata-sync

Keeps the navigation data of a WT9 Dynamic's Dynon SkyView up to date: it
downloads an [Airmate](https://www.airmate.aero) AIRAC cycle, lays the files out
exactly the way the Dynon expects them, and copies the result onto the USB stick
without rewriting the gigabytes that did not change.

Everything specific to a subscription or a machine — the Airmate customer id,
the Dynon serial, the AIRAC cycle, the local paths — lives in `config.toml`,
which is git-ignored. The code contains no ids.

## Requirements

- Python 3.11 or newer (the config reader uses the standard-library `tomllib`)
- `rsync`, for the copy to the USB stick
- An active Airmate subscription bound to your Dynon serial

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp config.example.toml config.toml
```

Then edit `config.toml`. The two values you have to fill in are in the
`[airmate]` section:

- `id` — the customer id in your personal download URLs
  (`https://www.airmate.aero/download/navdata/<id>/...`), visible on the Airmate
  download page once logged in.
- `serial` — the serial of the Dynon the subscription is bound to. It is the
  number embedded in the filenames Airmate offers you, as in
  `airmate_av_data_eu_2608_<serial>.dup` and `CHARTS-<serial>.key`.

If you would rather not keep those on disk, leave the placeholders in place and
export them instead; the environment always wins over the file:

```bash
export WT9_AIRMATE_ID=... WT9_AIRMATE_SERIAL=...
```

Every other setting is documented inline in
[`config.example.toml`](config.example.toml).

## Usage

```bash
./navdata-update.py                 # download the configured cycle, then stage it
./navdata-update.py --list          # show which files the config resolves to
./navdata-update.py --cycle 2609    # try the next cycle without editing the config
./navdata-update.py --skip-download # rebuild the staging folder from the cache
./navdata-update.py --sync          # ...and rsync it onto the USB stick
```

Without `--sync` the run stops after staging and prints the exact `rsync`
command, so you can inspect the result first.

Downloads are resumable and run four at a time behind one global progress bar;
interrupting the script and running it again picks up where it left off. Files
that are already complete are skipped, with one deliberate exception: the
`CHARTS-*.key` file is always re-fetched, because its contents change every
cycle while its size stays identical.

## Keeping the configuration current

Two things drift and need a manual edit:

- **`data.cycle`** — the AIRAC cycle, as `<two-digit year><two-digit cycle>`
  (`2608` is the 8th cycle of 2026). It changes every 28 days.
- **`data.raster`** — raster VFR charts are named after their *edition* date
  (`VFR-FRANCE-OACI-16APR26.dcf`), which is unrelated to the AIRAC cycle. Copy
  the new filenames from the Airmate download page when an edition is published.

`--list` is the quick way to check what the current configuration points at
before starting a multi-gigabyte download.

## What ends up on the stick

```
AIRMATE_AV_DATA_EU_<cycle>_<serial>.DUP    navdata (uppercased, the Dynon is picky)
AIRMATE_OBSTACLE_DATA_EU_<cycle>_<serial>.DUP
CHARTS-<serial>.key                        unlocks the chart and raster layers
ChartData/Plates/...                       approach plates, from the region zips
Raster/VFR-*.dcf                           raster VFR charts
```

The copy uses `rsync --checksum --inplace --no-whole-file`: the staging folder is
rebuilt from scratch every run, so timestamps are always new and the default
size+mtime comparison would recopy everything. Deciding by content instead means
only genuinely changed blocks are written — which is what keeps the update short
and easy on a nearly-full FAT-32 stick.

## Repository layout

```
navdata-update.py          entry point
config.example.toml        documented template for the git-ignored config.toml
wt9_navdata/
  config.py                reads config.toml, applies env overrides, validates
  catalog.py               turns the config into the list of URLs to fetch
  download.py              resumable parallel downloader
  prepare.py               staging into the Dynon layout, and the rsync call
  cli.py                   argument parsing and the run sequence
tools/
  mbtiles_to_dcf.py        converts an MBTiles file into an Airmate-style .dcf
```

`tools/mbtiles_to_dcf.py` is a standalone experiment, not part of the update
flow. It builds a `.dcf` raster layer from any MBTiles source; note that a layer
is only displayed if a matching entry exists in `CHARTS-<serial>.key`, which the
script cannot create. Run `tools/mbtiles_to_dcf.py --help` for the options.

## A note on the data

The navdata is licensed per subscription and tied to your Dynon serial. Keep
`config.toml`, the downloads and the staging folder out of version control —
`.gitignore` already covers them. And, obviously: this is a personal convenience
script, so verify on the unit that the cycle you expect is the cycle it loaded.
