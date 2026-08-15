"""Standalone, non-destructive PDF page operations used alongside merging."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_page_ranges(specification: str, page_count: int) -> list[int]:
    """Convert a 1-based range such as ``1-3,5,8-`` into zero-based page indexes."""
    indexes: list[int] = []
    for token in (part.strip() for part in specification.split(",")):
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text) if start_text else 1
            end = int(end_text) if end_text else page_count
            if start < 1 or end < start or end > page_count:
                raise ValueError(f"Invalid page range: {token}")
            indexes.extend(range(start - 1, end))
        else:
            number = int(token)
            if number < 1 or number > page_count:
                raise ValueError(f"Page {number} is outside this PDF")
            indexes.append(number - 1)
    if not indexes:
        raise ValueError("Select at least one page.")
    return indexes


def transform_pdf(source_path: Path, output_path: Path, pages: str | None = None, rotate: int = 0, password: str | None = None) -> int:
    """Extract/rotate pages into a new PDF without modifying the source."""
    import pikepdf

    if rotate % 90:
        raise ValueError("Rotation must be a multiple of 90 degrees.")
    with pikepdf.Pdf.open(source_path, password=password or "") as source:
        selected = parse_page_ranges(pages, len(source.pages)) if pages else list(range(len(source.pages)))
        destination = pikepdf.Pdf.new()
        try:
            for index in selected:
                page = source.pages[index]
                destination.pages.append(page)
                if rotate:
                    copied = destination.pages[-1]
                    existing = int(copied.obj.get("/Rotate", 0))
                    copied.obj["/Rotate"] = (existing + rotate) % 360
            partial = output_path.with_suffix(output_path.suffix + ".partial")
            destination.save(partial)
            partial.replace(output_path)
        finally:
            destination.close()
    return len(selected)


def split_pdf(source_path: Path, output_path: Path, pages_per_file: int, password: str | None = None) -> list[Path]:
    import pikepdf

    if pages_per_file < 1:
        raise ValueError("Pages per file must be at least 1.")
    with pikepdf.Pdf.open(source_path, password=password or "") as source:
        output_paths: list[Path] = []
        for start in range(0, len(source.pages), pages_per_file):
            target = output_path.with_name(f"{output_path.stem}_part_{start // pages_per_file + 1:04d}{output_path.suffix}")
            destination = pikepdf.Pdf.new()
            try:
                destination.pages.extend(source.pages[start : start + pages_per_file])
                partial = target.with_suffix(target.suffix + ".partial")
                destination.save(partial)
                partial.replace(target)
                output_paths.append(target)
            finally:
                destination.close()
    return output_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Non-destructive OpenMerger PDF page tools")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pages", help="1-based ranges, e.g. 1-3,5,8-")
    parser.add_argument("--rotate", type=int, default=0, help="Rotation in degrees (multiple of 90)")
    parser.add_argument("--split", type=int, metavar="PAGES_PER_FILE")
    parser.add_argument("--password", help="Password for an encrypted input; never saved")
    args = parser.parse_args()
    if args.split:
        outputs = split_pdf(args.source, args.output, args.split, args.password)
        print("\n".join(str(path) for path in outputs))
    else:
        count = transform_pdf(args.source, args.output, args.pages, args.rotate, args.password)
        print(f"Created {args.output} with {count} page(s).")


if __name__ == "__main__":
    main()
