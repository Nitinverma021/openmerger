# OpenMerger

OpenMerger is a lightweight Windows PDF merger for very large folders. It scans a folder automatically, sorts PDFs by filename numbers, natural filename order, created timestamp, or modified timestamp, then creates either one merged PDF or many chunked PDFs such as 50 PDFs per merged file.

## Privacy

OpenMerger processes PDFs locally on your computer. It does not upload PDFs, filenames, passwords, or merge reports to any online service. Per-job passwords are used only while the current merge runs and are never stored in presets or job manifests.

## Features

- Scans all `.pdf` files from a folder, with optional subfolder scanning.
- Lets you add only the PDFs you choose from the file picker, or scan a folder and keep only the highlighted PDFs for a smaller merge.
- Auto-scans when you paste or browse to a valid folder path.
- Sorts by unique numbers in filenames, natural file name, created date, or modified date.
- Supports ascending or descending merge order for every sort mode.
- Creates one complete merged PDF or chunk files like `merged_part_0001.pdf`.
- Includes best-quality lossless compression using `pikepdf`.
- Offers optional strong compression when Ghostscript is installed on the PC.
- Lets you search, manually move, or remove PDFs before merging.
- Lets you insert an optional cover PDF and generate filename bookmarks in completed outputs.
- Supports a per-job PDF password for encrypted inputs; passwords are never persisted.
- Includes an integrated PDF Toolbox for extracting, rotating, splitting, protecting, unlocking, and updating PDF metadata.
- Converts PNG, JPG, JPEG, BMP, TIFF, and WebP images into a PDF locally.
- Inspects EXIF-style image metadata—including dimensions, camera details, date/time, GPS, copyright, and XMP presence—and can make a metadata-free image copy for privacy.
- Produces polished image PDFs with A4, Letter, poster, social portrait, and wide-banner page presets; choose margins, fit/crop behavior, and 150 or 300 DPI.
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

## Full offline installer

The normal portable build includes every built-in OpenMerger feature. DOCX-to-PDF and PPTX-to-PDF need an office rendering engine; use the **Full** installer to include LibreOffice so those tools work immediately on a new PC.

To build it, install Inno Setup, then:

1. Obtain the official LibreOffice Windows files and place the extracted runtime under `third_party\LibreOffice\program\soffice.exe`.
2. Include LibreOffice's license and notice files with that runtime, in line with its distribution requirements.
3. Run `build-full-installer.bat`.

The resulting `installer-output\OpenMerger-Full-Setup.exe` installs OpenMerger and the bundled engine together. At runtime OpenMerger first checks `engine\LibreOffice\program\soffice.exe`, then falls back to a separately installed LibreOffice. The full installer is substantially larger than the standard portable download because it includes the office engine.

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

## PDF Toolbox

Click **PDF toolbox** in the app header to run common one-file tasks without leaving OpenMerger. Every tool writes a new output file and refuses to overwrite its source:

- Extract selected pages or rotate them by 90°, 180°, or 270°.
- Split a PDF into fixed page-count parts.
- Convert one or more images into one PDF.
- Protect or unlock a PDF when you know the required password.
- Set title, author, and subject metadata.
- Inspect image metadata or create a metadata-free PNG/JPG/WebP/TIFF copy before sharing.
- Add page numbers, text watermarks, or a cover page; export pages as PNG; find/remove blank pages; and find duplicate page candidates.
- Convert PDF to DOCX or PPTX, Excel to CSV, and CSV to Excel locally. The Full installer also enables DOCX/PPTX to PDF without a separate download.

For image PDFs, **Print A4 + Fit with margins + 300 DPI** is the recommended setting for worksheets, forms, flyers, and printouts. Use **Poster**, **Social portrait**, or **Wide banner** for design-ready marketing exports; choose **Fill and crop** only when you want edge-to-edge artwork.

OCR, scanner acquisition, and deskewing require dedicated local engines such as OCRmyPDF/Tesseract or scanner drivers. They are intentionally not bundled, so OpenMerger remains a small, local-first application.

## Development

```text
pip install -r requirements.txt -r requirements-dev.txt -r requirements-build.txt
python -m pytest -q
ruff check .
```

The project pins runtime, build, and development dependencies for repeatable builds. The test suite covers natural sorting, atomic cancellation safety, validated resume behavior, and output/source collisions.

## Release notes

See [CHANGELOG.md](CHANGELOG.md). Windows code signing and a distribution license require an organization-owned signing certificate and an explicit license choice, so they are intentionally not guessed by the application.
