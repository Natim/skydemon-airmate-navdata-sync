"""Copy the staging folder onto one or more Dynon USB sticks.

rsync's default size+mtime check would recopy everything because the staging
folder is rebuilt from scratch on every run (fresh mtimes). The delta algorithm
(--no-whole-file) is also a poor fit for flash: it turns a changed file into
scattered block rewrites.

Instead we:

  * decide by content (blake2b), so only files whose bytes actually changed
    are written
  * write changed files in full, sequentially, in large chunks — flash likes
    that much more than random in-place deltas, and opening the dest with
    "wb" is still in-place (no temp copy), which matters on a nearly-full
    FAT-32 stick
  * drop dest files that are no longer in the staging tree
  * run one sequential writer per stick, in parallel, so LH and RH update
    at the same time without randomizing I/O on either device

aiofile (caio thread backend) is used because vfat/USB does not reliably
support kernel AIO / O_DIRECT; the thread pool still lets the two sticks
overlap.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path

from aiofile import async_open
from caio.thread_aio_asyncio import AsyncioContext
from rich.progress import BarColumn, Progress, ProgressColumn, TaskID, TextColumn, TimeRemainingColumn
from rich.text import Text

from .download import human_size

# 4 MiB sequential transfers: large enough to keep a USB controller busy,
# small enough to report progress and overlap two destinations.
CHUNK_SIZE = 4 * 1024 * 1024
HASH_NAME = "blake2b"


@dataclass(frozen=True)
class _FileInfo:
    rel: Path
    size: int
    digest: bytes


@dataclass
class SyncReport:
    target: Path
    copied: int = 0
    skipped: int = 0
    deleted: int = 0
    error: str | None = None


def relative_files(root: Path) -> list[Path]:
    """Files under root, as paths relative to it, in a stable order."""
    files, _dirs = _scan_tree(root)
    return files


def _scan_tree(
    root: Path,
    on_file: Callable[[int, Path], None] | None = None,
) -> tuple[list[Path], list[Path]]:
    """Files and directories under root, relative to it.

    Files are sorted. Directories are deepest-first so empty ones can be
    removed after extras are deleted. ``on_file(n, rel)`` runs as each file
    is discovered (``n`` starts at 1), before the sort.
    """
    if not root.is_dir():
        return [], []
    files: list[Path] = []
    dirs: list[Path] = []
    seen = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        rel = path.relative_to(root)
        if path.is_dir():
            dirs.append(rel)
            continue
        if path.is_file() and not path.name.startswith("."):
            files.append(rel)
            seen += 1
            if on_file is not None:
                on_file(seen, rel)
    files.sort()
    dirs.sort(key=lambda rel: len(rel.parts), reverse=True)
    return files, dirs


def _norm_rel(rel: Path) -> str:
    """FAT-32 is case-insensitive; Linux Path comparison is not."""
    return str(rel).casefold()


def prune_extras(
    target: Path,
    wanted: set[Path],
    on_scan: Callable[[int, Path], None] | None = None,
    on_purge: Callable[[int, int, Path], None] | None = None,
) -> list[Path]:
    """Delete dest files (and then empty dirs) that are not in the staging tree.

    ``on_scan`` follows the directory walk. ``on_purge(done, total, rel)`` follows
    each deletion and each directory-removal attempt.
    """
    wanted_norm = {_norm_rel(rel) for rel in wanted}
    files, dirs = _scan_tree(target, on_scan)
    extras = [rel for rel in files if _norm_rel(rel) not in wanted_norm]
    steps = len(extras) + len(dirs)
    done = 0
    for rel in extras:
        (target / rel).unlink(missing_ok=True)
        done += 1
        if on_purge is not None:
            on_purge(done, steps, rel)
    for rel in dirs:
        try:
            (target / rel).rmdir()
        except OSError:
            pass
        done += 1
        if on_purge is not None:
            on_purge(done, steps, rel)
    return extras


def describe_sync(prepared_dir: Path, usb_targets: tuple[Path, ...]) -> str:
    if not usb_targets:
        return (
            f"✅ Dossier prêt: {prepared_dir}\n"
            "   Renseignez paths.usb_targets dans config.toml pour la synchronisation."
        )
    lines = [f"✅ Dossier prêt: {prepared_dir}", "   Cibles USB:"]
    for target in usb_targets:
        status = "montée" if target.is_dir() else "absente"
        lines.append(f"   • {target} ({status})")
    lines.append("   Relancez avec --sync pour copier (fichiers identiques ignorés, sticks en parallèle).")
    return "\n".join(lines)


def sync(prepared_dir: Path, usb_targets: tuple[Path, ...]) -> int:
    """Copy the staging folder onto every configured stick. Returns an exit code."""
    return asyncio.run(_sync(prepared_dir, usb_targets))


async def _sync(prepared_dir: Path, usb_targets: tuple[Path, ...]) -> int:
    if not usb_targets:
        print("❌ aucune cible USB dans la configuration")
        return 1

    mounted = [target for target in usb_targets if target.is_dir()]
    missing = [target for target in usb_targets if not target.is_dir()]
    for target in missing:
        print(f"❌ {target} introuvable: la clé USB est-elle montée ?")
    if not mounted:
        return 1

    source_files = relative_files(prepared_dir)
    if not source_files:
        print(f"❌ {prepared_dir} est vide, rien à copier")
        return 1

    started = time.perf_counter()
    async with AsyncioContext(max_requests=32) as ctx:
        manifest = await _index_source(prepared_dir, source_files, ctx)
        with _usb_progress() as progress:
            task_ids = [
                progress.add_task(
                    description=target.name or str(target),
                    total=max(len(manifest), 1),
                    label=target.name or str(target),
                    phase="Vérif.",
                    current="",
                    unit="fichier",
                )
                for target in mounted
            ]
            reports = await asyncio.gather(
                *(
                    _sync_target(prepared_dir, manifest, target, ctx, progress, task_id)
                    for target, task_id in zip(mounted, task_ids)
                )
            )
        print("💾 Vidage des caches disque...")
        os.sync()
    elapsed = time.perf_counter() - started

    failed = False
    for report in reports:
        if report.error:
            print(
                f"❌ {report.target}: {report.error} "
                f"({report.copied} copiés, {report.skipped} inchangés, "
                f"{report.deleted} supprimés)"
            )
            failed = True
        else:
            print(
                f"✅ {report.target}: "
                f"{report.copied} copiés, {report.skipped} inchangés, "
                f"{report.deleted} supprimés"
            )
    print(f"⏱️  Durée totale : {_format_duration(elapsed)}")
    if missing:
        failed = True
    return 1 if failed else 0


def _format_duration(seconds: float) -> str:
    """Wall-clock duration for the summary, e.g. ``1 h 2 min 3 s``."""
    whole = max(0, round(seconds))
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} h")
    if hours or minutes:
        parts.append(f"{minutes} min")
    parts.append(f"{secs} s")
    return " ".join(parts)


class _WorkColumn(ProgressColumn):
    """Bytes for copy/hash, file counts for verify/purge."""

    def render(self, task) -> Text:
        completed = float(task.completed or 0)
        total = float(task.total or 0)
        if task.fields.get("unit") == "fichier":
            if task.total is None:
                return Text(f"{int(completed)} fichiers")
            return Text(f"{int(completed)}/{int(total)} fichiers")
        return Text(f"{human_size(completed)}/{human_size(total)}")


class _RateColumn(ProgressColumn):
    def render(self, task) -> Text:
        speed = task.speed
        if speed is None:
            return Text("-")
        if task.fields.get("unit") == "fichier":
            return Text(f"{speed:.1f}/s")
        return Text(f"{human_size(speed)}/s")


def _usb_progress() -> Progress:
    """One live bar per USB stick (or a single bar for the source checksum)."""
    return Progress(
        TextColumn("[bold cyan]{task.fields[label]:<12}"),
        TextColumn("{task.fields[phase]:<8}"),
        BarColumn(bar_width=None),
        _WorkColumn(),
        _RateColumn(),
        TimeRemainingColumn(),
        TextColumn("{task.fields[current]}", style="dim", markup=False),
        expand=True,
        refresh_per_second=8,
    )


def _advance(progress: Progress, task_id: TaskID, n: int) -> None:
    progress.update(task_id, advance=n)


def _restart_phase(
    progress: Progress,
    task_id: TaskID,
    *,
    phase: str,
    total: float | None,
    unit: str,
) -> None:
    """Start a phase from zero. ``total=None`` keeps the bar open-ended.

    Progress.reset treats ``total=None`` as "keep the current total", so the
    directory walk (unknown length) has to assign it under the progress lock.
    """
    now = progress.get_time()
    with progress._lock:
        task = progress._tasks[task_id]
        task._reset()
        task.total = total
        task.completed = 0
        task.start_time = now
        task.finished_time = None
        task.fields.update(phase=phase, current="", unit=unit)
    progress.refresh()


def _finish(progress: Progress, task_id: TaskID, phase: str, current: str = "") -> None:
    total = 1.0
    for task in progress.tasks:
        if task.id == task_id:
            total = task.total or 1
            break
    progress.update(task_id, phase=phase, current=current, completed=total)


async def _index_source(prepared_dir: Path, files: list[Path], ctx: AsyncioContext) -> list[_FileInfo]:
    total = sum((prepared_dir / rel).stat().st_size for rel in files)
    with _usb_progress() as progress:
        task_id = progress.add_task(
            "Source",
            total=max(total, 1),
            label="Source",
            phase="Hash",
            current="",
            unit="B",
        )
        manifest: list[_FileInfo] = []
        for rel in files:
            path = prepared_dir / rel
            size = path.stat().st_size
            progress.update(task_id, current=str(rel), phase="Hash")
            digest = await _digest(path, ctx, lambda n: _advance(progress, task_id, n))
            manifest.append(_FileInfo(rel, size, digest))
        _finish(progress, task_id, "OK")
    return manifest


async def _sync_target(
    prepared_dir: Path,
    manifest: list[_FileInfo],
    target: Path,
    ctx: AsyncioContext,
    progress: Progress,
    task_id: TaskID,
) -> SyncReport:
    report = SyncReport(target)
    label = target.name or str(target)
    wanted = {info.rel for info in manifest}

    try:
        # Copy (and skip) first, then delete leftovers. Pruning tens of thousands
        # of plates up front blocked the event loop, froze both bars at 0 %, and
        # emptied the stick before anything was verified.
        to_copy: list[_FileInfo] = []
        for info in manifest:
            dest = target / info.rel
            progress.update(
                task_id,
                phase="Vérif.",
                current=str(info.rel),
            )
            if dest.is_file() and dest.stat().st_size == info.size:
                digest = await _digest(dest, ctx)
                if digest == info.digest:
                    report.skipped += 1
                    progress.update(task_id, advance=1)
                    continue
            to_copy.append(info)
            progress.update(task_id, advance=1)

        if to_copy:
            copy_total = sum(info.size for info in to_copy)
            progress.reset(task_id, total=max(copy_total, 1))
            progress.update(task_id, phase="Copie", current="", unit="B")
            for info in to_copy:
                progress.update(task_id, phase="Copie", current=str(info.rel))
                await _copy_file(
                    prepared_dir / info.rel,
                    target / info.rel,
                    ctx,
                    lambda n: _advance(progress, task_id, n),
                )
                report.copied += 1

        _restart_phase(progress, task_id, phase="Liste", total=None, unit="fichier")

        def on_scan(n: int, rel: Path) -> None:
            progress.update(task_id, completed=n, current=str(rel))

        purge_started = False

        def on_purge(done: int, total: int, rel: Path) -> None:
            nonlocal purge_started
            if not purge_started:
                _restart_phase(progress, task_id, phase="Purge", total=total, unit="fichier")
                purge_started = True
            progress.update(task_id, completed=done, current=str(rel))

        extras = await asyncio.to_thread(prune_extras, target, wanted, on_scan, on_purge)
        report.deleted = len(extras)
        if extras:
            progress.log(f"🗑️  [{label}] {len(extras)} fichiers superflus")
        _finish(progress, task_id, "OK")
    except OSError as exc:
        report.error = str(exc)
        _finish(progress, task_id, "Erreur", str(exc))
    return report


async def _digest(
    path: Path,
    ctx: AsyncioContext,
    on_bytes: Callable[[int], None] | None = None,
) -> bytes:
    digest = hashlib.new(HASH_NAME)
    async with async_open(path, "rb", context=ctx) as fh:
        async for chunk in fh.iter_chunked(CHUNK_SIZE):
            digest.update(chunk)
            if on_bytes is not None:
                on_bytes(len(chunk))
    return digest.digest()


async def _copy_file(
    source: Path,
    dest: Path,
    ctx: AsyncioContext,
    on_bytes: Callable[[int], None],
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncExitStack() as stack:
        src = await stack.enter_async_context(async_open(source, "rb", context=ctx))
        out = await stack.enter_async_context(async_open(dest, "wb", context=ctx))
        async for chunk in src.iter_chunked(CHUNK_SIZE):
            await out.write(chunk)
            on_bytes(len(chunk))
        await out.flush(sync_metadata=True)
