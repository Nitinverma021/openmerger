from pathlib import Path

import pikepdf

from pdf_fast_merger.core import PdfInfo, merge_collection, merge_paths, natural_key, sort_pdfs


def make_pdf(path: Path) -> PdfInfo:
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page(page_size=(100, 100))
    pdf.save(path)
    stat = path.stat()
    return PdfInfo(path, path.name, stat.st_size, stat.st_ctime, stat.st_mtime, ())


def test_natural_sorting() -> None:
    files = [
        PdfInfo(Path(name), name, 0, 0, 0, ())
        for name in ("page-10.pdf", "page-2.pdf", "page-1.pdf")
    ]
    assert [item.name for item in sort_pdfs(files, "name")] == ["page-1.pdf", "page-2.pdf", "page-10.pdf"]
    assert natural_key("page-10") > natural_key("page-2")


def test_merge_is_atomic_and_preserves_existing_on_cancellation(tmp_path: Path) -> None:
    first, second = make_pdf(tmp_path / "one.pdf"), make_pdf(tmp_path / "two.pdf")
    output = tmp_path / "merged.pdf"
    output.write_bytes(b"existing output")
    import threading

    stopped = threading.Event()
    stopped.set()
    result = merge_paths([first.path, second.path], output, batch_size=2, workers=1, stop_event=stopped)
    assert result.cancelled
    assert output.read_bytes() == b"existing output"
    assert not output.with_suffix(".pdf.partial").exists()


def test_resume_requires_matching_manifest_and_valid_chunk(tmp_path: Path) -> None:
    files = [make_pdf(tmp_path / f"{index}.pdf") for index in range(3)]
    output = tmp_path / "merged.pdf"
    initial = merge_collection(files, str(output), "chunks", 2, 2, 1)
    assert len(initial.outputs) == 2
    resumed = merge_collection(files, str(output), "chunks", 2, 2, 1, skip_existing=True)
    assert len(resumed.outputs) == 2
    changed = merge_collection(files, str(output), "chunks", 1, 2, 1, skip_existing=True)
    assert len(changed.outputs) == 3


def test_output_cannot_be_source(tmp_path: Path) -> None:
    source = make_pdf(tmp_path / "merged.pdf")
    try:
        merge_collection([source], str(source.path), "single", 1, 2, 1)
    except ValueError as exc:
        assert "source list" in str(exc)
    else:
        raise AssertionError("expected an output/source collision")
