"""Resumable, parallel downloads behind a single global progress bar."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import httpx
from tqdm import tqdm

from .catalog import RemoteFile

CHUNK_SIZE = 1024 * 1024
MAX_CONNECTIONS = 4


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024
    raise AssertionError("unreachable")


@dataclass
class _Job:
    """A file to fetch, with what is already on disk resolved up front."""

    file: RemoteFile
    dest: Path
    remote_size: int  # 0 when the server does not advertise a content-length
    local_size: int

    @property
    def complete(self) -> bool:
        return bool(self.remote_size) and self.local_size >= self.remote_size


async def run(files: list[RemoteFile], download_dir: Path) -> None:
    download_dir.mkdir(parents=True, exist_ok=True)
    limits = httpx.Limits(max_connections=MAX_CONNECTIONS)

    async with httpx.AsyncClient(http2=True, timeout=None, limits=limits) as client:
        jobs = await _plan(client, files, download_dir)

        progress = tqdm(
            total=sum(job.remote_size for job in jobs),
            initial=sum(job.local_size for job in jobs),
            unit="B",
            unit_scale=True,
            desc="Téléchargement global",
        )
        await asyncio.gather(*(_fetch(client, job, progress) for job in jobs))
        progress.close()


async def _plan(
    client: httpx.AsyncClient, files: list[RemoteFile], download_dir: Path
) -> list[_Job]:
    sizes = await asyncio.gather(*(_remote_size(client, f.url) for f in files))

    jobs = []
    for file, remote_size in zip(files, sizes):
        dest = download_dir / file.name
        if file.always_refresh:
            dest.unlink(missing_ok=True)
        local_size = dest.stat().st_size if dest.exists() else 0
        jobs.append(_Job(file, dest, remote_size, local_size))
    return jobs


async def _remote_size(client: httpx.AsyncClient, url: str) -> int:
    try:
        response = await client.head(url)
        return int(response.headers.get("content-length", 0))
    except (httpx.HTTPError, ValueError):
        return 0


async def _fetch(client: httpx.AsyncClient, job: _Job, progress: tqdm) -> None:
    if job.complete:
        tqdm.write(f"⏭️  {job.dest.name} déjà complet ({human_size(job.local_size)})")
        return

    job.dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {}

    if job.local_size:
        headers["Range"] = f"bytes={job.local_size}-"
        remaining = human_size(job.remote_size - job.local_size) if job.remote_size else "?"
        tqdm.write(
            f"↩️  Reprise {job.dest.name} "
            f"({human_size(job.local_size)}/{human_size(job.remote_size)}, "
            f"reste {remaining})"
        )
    else:
        tqdm.write(f"⬇️  Téléchargement {job.dest.name} ({human_size(job.remote_size)})")

    try:
        resumed = await _stream(client, job, headers, progress)

        # A 416 means the server disagrees with our idea of the file length, so
        # the partial file is unusable: drop it, un-count its bytes and restart.
        if not resumed:
            tqdm.write(f"⚠️  {job.dest.name} mismatch → re-téléchargement complet")
            job.dest.unlink(missing_ok=True)
            progress.update(-job.local_size)
            job.local_size = 0
            await _stream(client, job, {}, progress)

        tqdm.write(f"✅ {job.dest.name} terminé ({human_size(job.dest.stat().st_size)})")

    except httpx.HTTPError as exc:
        tqdm.write(f"❌ Erreur téléchargement {job.dest.name}: {exc}")


async def _stream(
    client: httpx.AsyncClient, job: _Job, headers: dict[str, str], progress: tqdm
) -> bool:
    """Append (or write) the response body to disk. False on a 416 rejection."""
    async with client.stream("GET", job.file.url, headers=headers) as response:
        if response.status_code == httpx.codes.REQUESTED_RANGE_NOT_SATISFIABLE:
            return False
        response.raise_for_status()

        with open(job.dest, "ab" if headers.get("Range") else "wb") as fh:
            async for chunk in response.aiter_bytes(CHUNK_SIZE):
                fh.write(chunk)
                progress.update(len(chunk))
    return True
