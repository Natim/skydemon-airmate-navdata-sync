#!/home/rhubscher/.virtualenvs/navdata/bin/python
import asyncio
import httpx
import shutil
import zipfile
from pathlib import Path
from tqdm import tqdm

# =========================
# CONFIG
# =========================

ID = "<YOUR_ID>"
BASE_DIR = Path("./downloads")
TARGET_DIR = Path("./downloads_prepared")

FILES = {
    # Core Dynon
    "navdata": f"https://www.airmate.aero/download/navdata/{ID}/airmate_av_data_eu_2607_008837.dup",
    "obstacles": f"https://www.airmate.aero/download/navdata/{ID}/airmate_obstacle_data_eu_2607_008837.dup",
    "charts_key": f"https://www.airmate.aero/download/navdata/{ID}/CHARTS-008837.key",

    # Plates
    "plates_fr": "https://www.airmate.aero/download/navdata/Plates/FR-Plates-2607.zip",
    "plates_europe": "https://www.airmate.aero/download/navdata/Plates/Europe-Plates-2607.zip",

    # Raster
    "vfr_fr": "https://www.airmate.aero/download/navdata/Raster/VFR-FRANCE-OACI-16APR26.dcf",
    "vfr_europe": "https://www.airmate.aero/download/navdata/Raster/VFR-EUROPE-HIRES-14MAY26.dcf",
    "denmark": "https://www.airmate.aero/download/navdata/Raster/VFR-DENMARK-NAVIAIR-14MAY26.dcf",
    "ireland": "https://www.airmate.aero/download/navdata/Raster/VFR-IRELAND-01JAN24.dcf",
    "uk": "https://www.airmate.aero/download/navdata/Raster/VFR-UK-01JAN24.dcf",
    "italy": "https://www.airmate.aero/download/navdata/Raster/VFR-ITALY-16APR26.dcf",
    "swiss": "https://www.airmate.aero/download/navdata/Raster/VFR-SWITZERLAND-19MAR26.dcf",
}

CHUNK_SIZE = 1024 * 1024  # 1MB


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


# =========================
# GET TOTAL SIZE
# =========================

async def get_file_size(client, url):
    try:
        r = await client.head(url)
        if "content-length" in r.headers:
            return int(r.headers["content-length"])
    except:
        pass
    return 0


# =========================
# DOWNLOAD (shared progress)
# =========================

async def download_file(client, url, dest, progress):
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Get remote size
    remote_size = 0
    try:
        r = await client.head(url)
        remote_size = int(r.headers.get("content-length", 0))
    except:
        pass

    existing_size = dest.stat().st_size if dest.exists() else 0

    # The .key file changes content every AIRAC cycle (chart filenames and
    # auth codes rotate) while keeping the exact same byte size. A size-only
    # "already complete" check would keep a stale key on disk, which makes the
    # Dynon silently hide any layer whose filename/code no longer matches.
    # Always fetch it fresh.
    if dest.suffix.lower() == ".key" and dest.exists():
        dest.unlink()
        existing_size = 0

    # ✅ Case 1: already complete → skip
    if remote_size and existing_size >= remote_size:
        tqdm.write(f"⏭️  {dest.name} déjà complet ({human_size(existing_size)})")
        return

    headers = {}
    mode = "wb"

    if existing_size > 0:
        headers["Range"] = f"bytes={existing_size}-"
        mode = "ab"
        remaining = human_size(remote_size - existing_size) if remote_size else "?"
        tqdm.write(
            f"↩️  Reprise {dest.name} "
            f"({human_size(existing_size)}/{human_size(remote_size)}, reste {remaining})"
        )
    else:
        tqdm.write(f"⬇️  Téléchargement {dest.name} ({human_size(remote_size)})")

    try:
        async with client.stream("GET", url, headers=headers) as response:

            # ✅ Handle 416 properly
            if response.status_code == 416:
                tqdm.write(f"⚠️  {dest.name} mismatch → re-download complet")
                dest.unlink(missing_ok=True)

                async with client.stream("GET", url) as response2:
                    response2.raise_for_status()

                    with open(dest, "wb") as f:
                        async for chunk in response2.aiter_bytes(CHUNK_SIZE):
                            f.write(chunk)
                            progress.update(len(chunk))
                tqdm.write(f"✅ {dest.name} terminé ({human_size(dest.stat().st_size)})")
                return

            response.raise_for_status()

            with open(dest, mode) as f:
                async for chunk in response.aiter_bytes(CHUNK_SIZE):
                    f.write(chunk)
                    progress.update(len(chunk))

        tqdm.write(f"✅ {dest.name} terminé ({human_size(dest.stat().st_size)})")

    except httpx.HTTPError as e:
        tqdm.write(f"❌ Erreur téléchargement {dest.name}: {e}")


# =========================
# DOWNLOAD ALL
# =========================

async def download_all():
    limits = httpx.Limits(max_connections=4)

    async with httpx.AsyncClient(http2=True, timeout=None, limits=limits) as client:

        # 1. calcul taille totale
        total_size = 0
        existing_total = 0

        for url in FILES.values():
            dest = BASE_DIR / Path(url).name
            size = await get_file_size(client, url)
            total_size += size

            if dest.exists():
                existing_total += dest.stat().st_size

        # 2. barre globale
        progress = tqdm(
            total=total_size,
            initial=existing_total,
            unit="B",
            unit_scale=True,
            desc="Téléchargement global",
        )

        # 3. téléchargements parallèles
        await asyncio.gather(*[
            download_file(client, url, BASE_DIR / Path(url).name, progress)
            for url in FILES.values()
        ])

        progress.close()


# =========================
# PREPARE STRUCTURE
# =========================

def prepare_structure():
    print("📦 Construction du dossier final...")

    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR)
    TARGET_DIR.mkdir()

    expected = {Path(url).name for url in FILES.values()}

    # DUP + KEY
    for name in sorted(expected):
        src = BASE_DIR / name
        if not src.is_file():
            continue
        if name.endswith(".dup"):
            (TARGET_DIR / name.upper()).write_bytes(src.read_bytes())
        elif name.endswith(".key"):
            (TARGET_DIR / name).write_bytes(src.read_bytes())

    # ZIP → ChartData
    for name in sorted(expected):
        if not name.endswith(".zip"):
            continue
        zip_file = BASE_DIR / name
        if not zip_file.is_file():
            continue
        print(f"📂 Extraction {zip_file.name}")
        with zipfile.ZipFile(zip_file, "r") as z:
            z.extractall(TARGET_DIR)

    # Raster
    raster_dir = TARGET_DIR / "Raster"
    raster_dir.mkdir(exist_ok=True)

    for name in sorted(expected):
        if not name.endswith(".dcf"):
            continue
        src = BASE_DIR / name
        if not src.is_file():
            continue
        (raster_dir / name).write_bytes(src.read_bytes())

    # --no-inc-recursive forces rsync to build the full file list before
    # transferring, so --info=progress2 shows a stable total and an accurate
    # overall percentage (otherwise the list grows as it goes).
    print(f"✅ Dossier prêt pour rsync: `rsync -avh --no-inc-recursive --info=progress2 --delete {TARGET_DIR}/ '/run/media/{ID.lower()}/LH D1000/'`")


# =========================
# MAIN
# =========================

async def main():
    BASE_DIR.mkdir(exist_ok=True)

    await download_all()
    prepare_structure()


if __name__ == "__main__":
    asyncio.run(main())
