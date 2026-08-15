"""Standalone, non-destructive PDF page operations used alongside merging."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

ImagePagePreset = Literal["original", "a4", "letter", "poster", "social", "banner"]
ImageFit = Literal["contain", "cover"]

PAGE_SIZES_INCHES: dict[ImagePagePreset, tuple[float, float] | None] = {
    "original": None,
    "a4": (8.2677, 11.6929),
    "letter": (8.5, 11.0),
    "poster": (11.0, 17.0),
    "social": (8.0, 10.0),
    "banner": (13.3333, 7.5),
}


def _ensure_new_output(source_path: Path, output_path: Path) -> None:
    if source_path.expanduser().resolve() == output_path.expanduser().resolve():
        raise ValueError("Choose a different output file; source PDFs are never overwritten.")


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
    _ensure_new_output(source_path, output_path)
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
    _ensure_new_output(source_path, output_path)
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


def images_to_pdf(
    image_paths: Iterable[Path],
    output_path: Path,
    page_preset: ImagePagePreset = "original",
    fit: ImageFit = "contain",
    margin_mm: float = 8,
    dpi: int = 150,
) -> int:
    """Create a print-ready PDF from images, with optional page-layout presets."""
    from PIL import Image

    if page_preset not in PAGE_SIZES_INCHES:
        raise ValueError("Choose a valid page preset.")
    if fit not in {"contain", "cover"}:
        raise ValueError("Image fit must be contain or cover.")
    if margin_mm < 0:
        raise ValueError("Margin cannot be negative.")
    if dpi not in {150, 300}:
        raise ValueError("DPI must be 150 or 300.")
    paths = list(image_paths)
    if output_path.expanduser().resolve() in {path.expanduser().resolve() for path in paths}:
        raise ValueError("Choose a different output file; source images are never overwritten.")
    images = []
    try:
        for path in paths:
            with Image.open(path) as source:
                image = source.convert("RGB")
                images.append(_layout_image(image, page_preset, fit, margin_mm, dpi))
                image.close()
        if not images:
            raise ValueError("Choose at least one image.")
        partial = output_path.with_suffix(output_path.suffix + ".partial")
        images[0].save(partial, "PDF", save_all=True, append_images=images[1:], resolution=float(dpi))
        partial.replace(output_path)
        return len(images)
    finally:
        for image in images:
            image.close()


def _layout_image(image: object, page_preset: ImagePagePreset, fit: ImageFit, margin_mm: float, dpi: int) -> object:
    from PIL import Image

    page_inches = PAGE_SIZES_INCHES[page_preset]
    if page_inches is None:
        return image.copy()
    page_width, page_height = page_inches
    if page_preset in {"a4", "letter", "poster"} and image.width > image.height and page_height > page_width:
        page_width, page_height = page_height, page_width
    canvas_size = (round(page_width * dpi), round(page_height * dpi))
    margin = round((margin_mm / 25.4) * dpi)
    available_width = max(1, canvas_size[0] - 2 * margin)
    available_height = max(1, canvas_size[1] - 2 * margin)
    scale = max(available_width / image.width, available_height / image.height) if fit == "cover" else min(available_width / image.width, available_height / image.height)
    resized = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", canvas_size, "white")
    x = margin + (available_width - resized.width) // 2
    y = margin + (available_height - resized.height) // 2
    canvas.paste(resized, (x, y))
    resized.close()
    return canvas


def update_metadata(source_path: Path, output_path: Path, title: str = "", author: str = "", subject: str = "", password: str | None = None) -> None:
    import pikepdf

    _ensure_new_output(source_path, output_path)
    with pikepdf.Pdf.open(source_path, password=password or "") as document:
        if title:
            document.docinfo["/Title"] = title
        if author:
            document.docinfo["/Author"] = author
        if subject:
            document.docinfo["/Subject"] = subject
        partial = output_path.with_suffix(output_path.suffix + ".partial")
        document.save(partial)
        partial.replace(output_path)


def protect_pdf(source_path: Path, output_path: Path, user_password: str, owner_password: str | None = None, source_password: str | None = None) -> None:
    import pikepdf

    if not user_password:
        raise ValueError("Enter a password to protect the PDF.")
    _ensure_new_output(source_path, output_path)
    with pikepdf.Pdf.open(source_path, password=source_password or "") as document:
        partial = output_path.with_suffix(output_path.suffix + ".partial")
        document.save(partial, encryption=pikepdf.Encryption(user=user_password, owner=owner_password or user_password, R=6))
        partial.replace(output_path)


def unlock_pdf(source_path: Path, output_path: Path, password: str) -> None:
    import pikepdf

    if not password:
        raise ValueError("Enter the current PDF password to unlock it.")
    _ensure_new_output(source_path, output_path)
    with pikepdf.Pdf.open(source_path, password=password) as document:
        partial = output_path.with_suffix(output_path.suffix + ".partial")
        document.save(partial, encryption=False)
        partial.replace(output_path)


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
