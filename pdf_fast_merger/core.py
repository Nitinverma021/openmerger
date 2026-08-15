from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

SortMode = Literal["number", "name", "created", "modified"]
SortDirection = Literal["ascending", "descending"]
MergeMode = Literal["single", "chunks"]
CompressionMode = Literal["none", "lossless", "strong"]
ProgressCallback = Callable[[int, int, str], None]
ControlCallback = Callable[[], None]


@dataclass(frozen=True)
class PdfInfo:
    path: Path
    name: str
    size: int
    created: float
    modified: float
    numbers: tuple[int, ...]

    @property
    def created_label(self) -> str:
        return format_timestamp(self.created)

    @property
    def size_label(self) -> str:
        return format_size(self.size)


@dataclass(frozen=True)
class MergeFailure:
    path: Path
    error: str


@dataclass(frozen=True)
class MergeResult:
    outputs: list[Path]
    failures: list[MergeFailure]
    report_path: Path | None = None
    manifest_path: Path | None = None
    warnings: list[str] | None = None
    cancelled: bool = False


class MergeCancelled(RuntimeError):
    """Raised internally when a user stops an in-progress merge."""


def format_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value).strftime("%d-%m-%Y %I:%M:%S %p")


def format_size(size: int) -> str:
    labels = ("B", "KB", "MB", "GB", "TB")
    amount = float(size)
    for label in labels:
        if amount < 1024 or label == labels[-1]:
            return f"{amount:.0f} {label}" if label == "B" else f"{amount:.1f} {label}"
        amount /= 1024
    return f"{size} B"


def natural_key(value: str) -> tuple[object, ...]:
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value))


def filename_numbers(value: str) -> tuple[int, ...]:
    return tuple(int(match) for match in re.findall(r"\d+", Path(value).stem))


def created_timestamp(stat: os.stat_result) -> float:
    return float(getattr(stat, "st_birthtime", stat.st_ctime))


def scan_folder(
    folder: str,
    recursive: bool,
    sort_mode: SortMode,
    sort_direction: SortDirection = "ascending",
) -> list[PdfInfo]:
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Folder path does not exist.")

    iterator: Iterable[Path] = root.rglob("*") if recursive else root.iterdir()
    files: list[PdfInfo] = []
    for path in iterator:
        if not path.is_file() or path.suffix.casefold() != ".pdf":
            continue
        stat = path.stat()
        files.append(
            PdfInfo(
                path=path,
                name=path.name,
                size=stat.st_size,
                created=created_timestamp(stat),
                modified=float(stat.st_mtime),
                numbers=filename_numbers(path.name),
            )
        )
    return sort_pdfs(files, sort_mode, sort_direction)


def sort_pdfs(
    files: list[PdfInfo],
    sort_mode: SortMode,
    sort_direction: SortDirection = "ascending",
) -> list[PdfInfo]:
    reverse = sort_direction == "descending"
    if sort_mode == "created":
        return sorted(files, key=lambda item: (item.created, natural_key(item.name), str(item.path).casefold()), reverse=reverse)
    if sort_mode == "modified":
        return sorted(files, key=lambda item: (item.modified, natural_key(item.name), str(item.path).casefold()), reverse=reverse)
    if sort_mode == "name":
        return sorted(files, key=lambda item: (natural_key(item.name), item.created, str(item.path).casefold()), reverse=reverse)
    return sorted(
        files,
        key=lambda item: (
            0 if item.numbers else 1,
            item.numbers,
            natural_key(item.name),
            item.created,
            str(item.path).casefold(),
        ),
        reverse=reverse,
    )


def merge_collection(
    files: list[PdfInfo],
    output_path: str,
    merge_mode: MergeMode,
    chunk_size: int,
    batch_size: int,
    workers: int,
    compression: CompressionMode = "lossless",
    skip_existing: bool = False,
    stop_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
    bookmarks: bool = False,
    password: str | None = None,
) -> MergeResult:
    if not files:
        raise ValueError("No PDF files found.")
    if batch_size < 2:
        raise ValueError("Internal batch size must be at least 2.")
    if workers < 1:
        raise ValueError("Worker count must be at least 1.")

    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    groups = [files]
    if merge_mode == "chunks":
        if chunk_size < 1:
            raise ValueError("Chunk size must be at least 1.")
        groups = [files[index : index + chunk_size] for index in range(0, len(files), chunk_size)]

    planned_outputs = {output if merge_mode == "single" else _chunk_output_path(output, index) for index in range(1, len(groups) + 1)}
    source_paths = {item.path.expanduser().resolve() for item in files}
    collisions = planned_outputs & source_paths
    if collisions:
        raise ValueError(f"Output PDF is also in the source list: {next(iter(collisions)).name}. Rescan after removing old output files.")

    manifest_path = _manifest_path(output)
    job = _job_definition(files, merge_mode, chunk_size, batch_size, compression, bookmarks)
    manifest = _load_manifest(manifest_path)
    valid_resume = bool(manifest and manifest.get("job") == job)
    if skip_existing and manifest and not valid_resume and progress:
        progress(0, 1, "Existing resume data does not match this job; rebuilding outputs")

    total_units = sum(_estimate_units(len(group), batch_size) for group in groups)
    completed_units = 0
    outputs: list[Path] = []
    failures: list[MergeFailure] = []

    for group_index, group in enumerate(groups, start=1):
        target = output if merge_mode == "single" else _chunk_output_path(output, group_index)
        group_id = _group_digest(group)
        completed = manifest.get("completed", {}) if valid_resume and manifest else {}
        if skip_existing and completed.get(str(group_index)) == group_id and _is_valid_pdf(target):
            outputs.append(target)
            completed_units += _estimate_units(len(group), batch_size)
            if progress:
                progress(completed_units, total_units, f"Skipped existing {target.name}")
            continue

        def report(done: int, total: int, message: str) -> None:
            if progress:
                progress(completed_units + done, total_units, f"{message} ({group_index}/{len(groups)})")

        result = merge_paths(
            [item.path for item in group],
            target,
            batch_size,
            workers,
            compression,
            stop_event,
            pause_event,
            report,
            password,
        )
        failures.extend(result.failures)
        if result.cancelled:
            _write_manifest(manifest_path, job, completed)
            return MergeResult(outputs, failures, write_failure_report(output.parent, failures) if failures else None, manifest_path, cancelled=True)
        completed_units += _estimate_units(len(group), batch_size)
        if target.exists():
            if bookmarks:
                _add_file_bookmarks(target, group, password)
            outputs.append(target)
            completed[str(group_index)] = group_id
            _write_manifest(manifest_path, job, completed)
        if progress:
            progress(completed_units, total_units, f"Saved {target.name}")

    report_path = write_failure_report(output.parent, failures) if failures else None
    return MergeResult(outputs, failures, report_path, manifest_path)


def merge_paths(
    input_paths: list[Path],
    output_path: Path,
    batch_size: int,
    workers: int,
    compression: CompressionMode = "lossless",
    stop_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
    password: str | None = None,
) -> MergeResult:
    normalized_inputs = [Path(path).expanduser().resolve() for path in input_paths]
    output = Path(output_path).expanduser().resolve()
    if output in normalized_inputs:
        raise ValueError("Output file cannot be one of the source PDFs.")

    output.parent.mkdir(parents=True, exist_ok=True)
    total = _estimate_units(len(normalized_inputs), batch_size)
    completed = 0
    failures: list[MergeFailure] = []

    def control() -> None:
        if stop_event and stop_event.is_set():
            raise MergeCancelled("Merge cancelled by user.")
        while pause_event and pause_event.is_set():
            if stop_event and stop_event.is_set():
                raise MergeCancelled("Merge cancelled by user.")
            threading.Event().wait(0.2)

    partial = output.with_suffix(output.suffix + ".partial")
    try:
        if partial.exists():
            partial.unlink()
        # Strong compression is intentionally applied only once to the completed output.
        intermediate_compression: CompressionMode = "lossless" if compression == "strong" else compression
        if len(normalized_inputs) <= batch_size:
            control()
            _merge_batch(normalized_inputs, partial, intermediate_compression, failures, control, password)
            control()
            _apply_final_compression(partial, compression)
            os.replace(partial, output)
            if progress:
                progress(total, total, "Merge complete")
            return MergeResult([output] if output.exists() else [], failures)

        with tempfile.TemporaryDirectory(prefix="openmerger-", dir=output.parent) as temp_root:
            temp_dir = Path(temp_root)
            current = normalized_inputs
            round_number = 1

            while len(current) > 1:
                control()
                batches = [current[index : index + batch_size] for index in range(0, len(current), batch_size)]
                tasks = [(batch, temp_dir / f"round-{round_number}-{index}.pdf") for index, batch in enumerate(batches, start=1)]
                max_workers = max(1, min(workers, len(tasks)))

                with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pdf-merge") as executor:
                    results = executor.map(
                        lambda task: _merge_batch(task[0], task[1], intermediate_compression, failures, control, password),
                        tasks,
                    )
                    next_round = []
                    for batch, result in zip(batches, results):
                        if result.exists():
                            next_round.append(result)
                        completed += len(batch)
                        if progress:
                            progress(completed, total, f"Merging {len(batch)} PDFs")
                if not next_round:
                    raise RuntimeError("No valid PDFs could be merged.")

                current = next_round
                round_number += 1

            control()
            shutil.copyfile(current[0], partial)
            control()
            _apply_final_compression(partial, compression)
            os.replace(partial, output)
        if progress:
            progress(total, total, "Merge complete")
        return MergeResult([output] if output.exists() else [], failures)
    except MergeCancelled:
        if partial.exists():
            partial.unlink()
        return MergeResult([], failures, cancelled=True)


def _merge_batch(
    paths: list[Path],
    output: Path,
    compression: CompressionMode,
    failures: list[MergeFailure],
    control: ControlCallback,
    password: str | None = None,
) -> Path:
    if len(paths) == 1:
        control()
        if compression in {"lossless", "strong"}:
            try:
                _compress_pdf(paths[0], output, compression, password)
            except Exception as exc:
                failures.append(MergeFailure(paths[0], str(exc)))
        else:
            shutil.copyfile(paths[0], output)
        return output

    import pikepdf

    destination = pikepdf.Pdf.new()
    try:
        for path in paths:
            control()
            try:
                with pikepdf.Pdf.open(path, password=password or "") as source:
                    destination.pages.extend(source.pages)
            except Exception as exc:
                failures.append(MergeFailure(path, str(exc)))
        destination.save(output, **_save_options(compression))
    finally:
        destination.close()
    return output


def _compress_pdf(input_path: Path, output: Path, compression: CompressionMode, password: str | None = None) -> None:
    import pikepdf

    with pikepdf.Pdf.open(input_path, password=password or "") as source:
        source.save(output, **_save_options(compression))


def _save_options(compression: CompressionMode) -> dict[str, object]:
    if compression == "none":
        return {}
    import pikepdf

    return {
        "compress_streams": True,
        "object_stream_mode": pikepdf.ObjectStreamMode.generate,
        "recompress_flate": True,
    }


def _apply_final_compression(output: Path, compression: CompressionMode) -> None:
    if compression != "strong" or not output.exists():
        return
    ghostscript = shutil.which("gswin64c") or shutil.which("gswin32c") or shutil.which("gs")
    if not ghostscript:
        return
    compressed = output.with_suffix(output.suffix + ".compressed")
    result = subprocess.run(
        [
            ghostscript,
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.5",
            "-dPDFSETTINGS=/ebook",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={compressed}",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and compressed.exists() and compressed.stat().st_size > 0:
        os.replace(compressed, output)
    elif compressed.exists():
        compressed.unlink()


def ghostscript_available() -> bool:
    return bool(shutil.which("gswin64c") or shutil.which("gswin32c") or shutil.which("gs"))


def _manifest_path(output: Path) -> Path:
    return output.with_name(f"{output.stem}.openmerger.json")


def _job_definition(
    files: list[PdfInfo],
    merge_mode: MergeMode,
    chunk_size: int,
    batch_size: int,
    compression: CompressionMode,
    bookmarks: bool,
) -> dict[str, object]:
    return {
        "version": 1,
        "mode": merge_mode,
        "chunk_size": chunk_size,
        "batch_size": batch_size,
        "compression": compression,
        "bookmarks": bookmarks,
        "sources": [
            {"path": str(item.path), "size": item.size, "modified": item.modified}
            for item in files
        ],
    }


def _add_file_bookmarks(output: Path, files: list[PdfInfo], password: str | None = None) -> None:
    """Add a top-level bookmark for each source PDF after a completed merge."""
    import pikepdf

    partial = output.with_suffix(output.suffix + ".bookmarks.partial")
    with pikepdf.Pdf.open(output) as document:
        with document.open_outline() as outline:
            outline.root.clear()
            page_number = 0
            for item in files:
                try:
                    with pikepdf.Pdf.open(item.path, password=password or "") as source:
                        pages = len(source.pages)
                except Exception:
                    continue
                if pages:
                    outline.root.append(pikepdf.OutlineItem(item.name, page_number))
                    page_number += pages
        document.save(partial)
    os.replace(partial, output)


def _group_digest(group: list[PdfInfo]) -> str:
    digest = hashlib.sha256()
    for item in group:
        digest.update(str(item.path).encode("utf-8", "surrogatepass"))
        digest.update(f"|{item.size}|{item.modified}".encode())
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _write_manifest(path: Path, job: dict[str, object], completed: object) -> None:
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps({"job": job, "completed": completed}, indent=2), encoding="utf-8")
    os.replace(partial, path)


def _is_valid_pdf(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        import pikepdf
        with pikepdf.Pdf.open(path):
            return True
    except Exception:
        return False


def _chunk_output_path(output: Path, index: int) -> Path:
    return output.with_name(f"{output.stem}_part_{index:04d}{output.suffix}")


def write_failure_report(folder: Path, failures: list[MergeFailure]) -> Path:
    report = folder / "failed_pdfs.txt"
    lines = ["Failed PDFs", "===========", ""]
    for failure in failures:
        lines.append(f"{failure.path}\t{failure.error}")
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def _estimate_units(file_count: int, batch_size: int) -> int:
    total = 0
    remaining = file_count
    while remaining > 1:
        total += remaining
        remaining = (remaining + batch_size - 1) // batch_size
    return max(total, 1)
