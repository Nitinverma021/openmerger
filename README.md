# OpenMerger

OpenMerger is a lightweight Windows PDF merger for very large folders. It scans a folder automatically, sorts PDFs by filename numbers, natural filename order, created timestamp, or modified timestamp, then creates either one merged PDF or many chunked PDFs such as 50 PDFs per merged file.

## Features

- Scans all `.pdf` files from a folder, with optional subfolder scanning.
- Auto-scans when you paste or browse to a valid folder path.
- Sorts by unique numbers in filenames, natural file name, created date, or modified date.
- Supports ascending or descending merge order for every sort mode.
- Creates one complete merged PDF or chunk files like `merged_part_0001.pdf`.
- Includes best-quality lossless compression using `pikepdf`.
- Offers optional strong compression when Ghostscript is installed on the PC.
- Lets you search, manually move, or remove PDFs before merging.
- Lets you insert an optional cover PDF and generate filename bookmarks in completed outputs.
- Supports a per-job PDF password for encrypted inputs; passwords are never persisted.
- Can pause/cancel long merges and resume chunk jobs by skipping existing parts.
- Saves `failed_pdfs.txt` if corrupted PDFs are skipped.
- Saves `duplicate_pdfs.txt` for same-name and same-size duplicate candidates.
- Uses low-resource defaults for older PCs: 1 worker and 50 PDFs per internal batch.
- Uses `pikepdf`, which is usually faster and safer than pure-Python PDF libraries.
- Writes every output atomically, so an interrupted job does not overwrite an existing PDF.
- Stores a verified `.openmerger.json` job manifest; resume only skips valid chunks from the same source list and settings.
- Includes a command-line interface, safe watch-folder mode, and separate non-destructive page extract/rotate/split tools.
- Saves desktop presets and the ten most recent completed jobs locally under `%APPDATA%\\OpenMerger`.

## Run on Windows

Double-click:

```text
start-windows.bat
```

This creates `.venv-windows`, installs dependencies, and starts the app.

## Build Windows EXE

Double-click:

```text
build-windows.bat
```

The EXE is created at:

```text
dist\OpenMerger\OpenMerger.exe
```

Keep the full `dist\OpenMerger` folder together when moving it to another PC.

## Recommended settings for 50,000 PDFs

- For old/slow PCs: keep `Workers` as `1`, `Internal batch` as `50`.
- For chunk output: choose `Make chunk PDFs` and set `PDFs per chunk` to `50` or any number you need.
- For one large PDF: choose `Make one complete merged PDF`, but make sure the drive has enough free space.
- Keep `Auto scan folder` enabled if you want PDFs to load as soon as a valid folder path is selected.
- Choose `Ascending` or `Descending` beside the sort option to control the exact merge order.
- Keep `Best quality compression` enabled for safe lossless compression without lowering image quality.
- Use `Strong compression` only when smaller scanned PDFs matter more than maximum image quality.
- Keep `Resume/skip existing chunks` enabled when creating many chunk files, so interrupted work can continue.
- Use the status log and `failed_pdfs.txt` to find corrupted source PDFs after a long merge.

Source PDFs are never modified. Temporary merge files are created beside the output and removed automatically.

## Command line and automation

After activating the environment, merge a folder without the desktop interface:

```text
python -m pdf_fast_merger.cli "C:\\Scans" "D:\\Output\\merged.pdf" --recursive --chunks 50 --resume
```

Available options include `--sort`, `--descending`, `--batch-size`, `--workers`, `--compression`, `--password`, and `--json`.
Use `--watch 10` to poll a folder every 10 seconds; put output files outside the watched folder.

Page utilities are deliberately separate from merging and never edit the input PDF:

```text
python -m pdf_fast_merger.operations source.pdf output.pdf --pages "1-3,5,8-" --rotate 90
python -m pdf_fast_merger.operations source.pdf split.pdf --split 25
```

Encrypted input can be opened with the optional `--password`; it is never stored in presets, manifests, or reports.

## Development

```text
pip install -r requirements.txt -r requirements-dev.txt -r requirements-build.txt
python -m pytest -q
ruff check .
```

The project pins runtime, build, and development dependencies for repeatable builds. The test suite covers natural sorting, atomic cancellation safety, validated resume behavior, and output/source collisions.

## Release notes

See [CHANGELOG.md](CHANGELOG.md). Windows code signing and a distribution license require an organization-owned signing certificate and an explicit license choice, so they are intentionally not guessed by the application.
