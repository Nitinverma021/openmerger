from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .core import merge_collection, scan_folder


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge PDFs locally with OpenMerger.")
    parser.add_argument("input", type=Path, help="Source folder")
    parser.add_argument("output", type=Path, help="Output PDF path")
    parser.add_argument("--recursive", action="store_true", help="Include subfolders")
    parser.add_argument("--sort", choices=("number", "name", "created", "modified"), default="number")
    parser.add_argument("--descending", action="store_true")
    parser.add_argument("--chunks", type=int, metavar="COUNT", help="Create a PDF for each COUNT sources")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--compression", choices=("none", "lossless", "strong"), default="lossless")
    parser.add_argument("--resume", action="store_true", help="Resume only verified chunks from a matching job manifest")
    parser.add_argument("--password", help="Password for encrypted source PDFs; never written to the manifest")
    parser.add_argument("--watch", type=float, metavar="SECONDS", help="Watch the folder and process when new PDFs appear")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable result")
    return parser


def _run(args: argparse.Namespace) -> int:
    files = scan_folder(str(args.input), args.recursive, args.sort, "descending" if args.descending else "ascending")
    if not files:
        print("No PDF files found.")
        return 1

    def progress(done: int, total: int, message: str) -> None:
        print(f"[{done}/{total}] {message}")

    result = merge_collection(
        files,
        str(args.output),
        "chunks" if args.chunks else "single",
        args.chunks or len(files),
        args.batch_size,
        args.workers,
        args.compression,
        args.resume,
        progress=progress,
        password=args.password,
    )
    payload = {
        "cancelled": result.cancelled,
        "outputs": [str(path) for path in result.outputs],
        "failures": [{"path": str(item.path), "error": item.error} for item in result.failures],
        "manifest": str(result.manifest_path) if result.manifest_path else None,
    }
    print(json.dumps(payload, indent=2) if args.json else f"Created {len(result.outputs)} output(s); skipped {len(result.failures)} invalid source(s).")
    return 0 if result.outputs and not result.cancelled else 1


def main() -> None:
    args = _parser().parse_args()
    if not args.watch:
        raise SystemExit(_run(args))
    last_signature: tuple[tuple[str, int, float], ...] | None = None
    print(f"Watching {args.input}. Press Ctrl+C to stop.")
    try:
        while True:
            files = scan_folder(str(args.input), args.recursive, args.sort, "descending" if args.descending else "ascending")
            signature = tuple((str(item.path), item.size, item.modified) for item in files)
            if files and signature != last_signature:
                _run(args)
                last_signature = signature
            time.sleep(max(1.0, args.watch))
    except KeyboardInterrupt:
        print("Watch stopped.")


if __name__ == "__main__":
    main()
