from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .core import MergeResult, PdfInfo, format_size, ghostscript_available, merge_collection, scan_folder
from .operations import (
    add_page_numbers,
    add_text_watermark,
    create_cover_page,
    csv_to_excel,
    excel_to_csv,
    find_duplicate_pages,
    image_metadata_reports,
    images_to_pdf,
    office_to_pdf,
    pdf_to_docx,
    pdf_to_images,
    pdf_to_pptx,
    protect_pdf,
    remove_blank_pages,
    remove_image_metadata,
    split_pdf,
    transform_pdf,
    unlock_pdf,
    update_metadata,
)

SORT_LABELS = {
    "Number in filename": "number",
    "File name": "name",
    "Created date": "created",
    "Modified date": "modified",
}

DIRECTION_LABELS = {
    "Ascending": "ascending",
    "Descending": "descending",
}

COMPRESSION_LABELS = {
    "Best quality compression": "lossless",
    "Strong compression (may reduce quality)": "strong",
    "No compression": "none",
}

TOOL_OUTPUT_SPECS = {
    "PDF to DOCX": (".docx", "Word documents", "*.docx"),
    "Excel to CSV": (".csv", "CSV files", "*.csv"),
    "CSV to Excel": (".xlsx", "Excel workbooks", "*.xlsx"),
    "PDF to PPTX": (".pptx", "PowerPoint files", "*.pptx"),
    "Remove image metadata": (".png", "PNG image", "*.png"),
}


class PdfMergerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("OpenMerger")
        self.geometry("1080x760")
        self.minsize(900, 620)
        self.configure(background="#f4f7fb")

        self.files: list[PdfInfo] = []
        self.visible_files: list[PdfInfo] = []
        self.visible_indexes: list[int] = []
        self.page_index = 0
        self.page_size = 500
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.log_messages: list[str] = []
        self.log_window: tk.Toplevel | None = None
        self.log_box: tk.Text | None = None
        self.toolbox_window: tk.Toplevel | None = None
        app_data = Path(os.environ.get("APPDATA", Path.home() / ".openmerger")) / "OpenMerger"
        self.settings_path = app_data / "settings.json"

        self.folder_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(Path.home() / "Desktop" / "merged.pdf"))
        self.cover_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.sort_var = tk.StringVar(value="Number in filename")
        self.direction_var = tk.StringVar(value="Ascending")
        self.compression_var = tk.StringVar(value="Best quality compression")
        self.search_var = tk.StringVar()
        self.resume_var = tk.BooleanVar(value=True)
        self.bookmark_var = tk.BooleanVar(value=False)
        self.recursive_var = tk.BooleanVar(value=False)
        self.auto_scan_var = tk.BooleanVar(value=True)
        self.mode_var = tk.StringVar(value="chunks")
        self.chunk_var = tk.IntVar(value=50)
        self.batch_var = tk.IntVar(value=50)
        self.worker_var = tk.IntVar(value=1)
        self.status_var = tk.StringVar(value="Choose a folder to begin.")
        self.summary_var = tk.StringVar(value="No PDFs loaded yet")
        self.progress_var = tk.DoubleVar(value=0)
        self._auto_scan_after: str | None = None
        self._refresh_after: str | None = None
        self._scan_generation = 0
        self._merge_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._drag_item: str | None = None

        self._configure_style()
        self._build()
        self.folder_var.trace_add("write", self._queue_auto_scan)
        self.search_var.trace_add("write", self._queue_refresh)
        self.bind("<Control-o>", lambda _event: self._browse_folder())
        self.bind("<Control-p>", lambda _event: self._add_selected_pdfs())
        self.bind("<Control-Return>", lambda _event: self._merge())
        self.bind("<Delete>", lambda _event: self._remove_selected())
        self.bind("<Control-f>", self._focus_search)
        self.after(150, self._drain_events)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        base_font = ("Segoe UI", 10)
        style.configure(".", font=base_font, background="#f4f7fb", foreground="#172033")
        style.configure("App.TFrame", background="#f4f7fb")
        style.configure("Header.TFrame", background="#172a46")
        style.configure("HeaderTitle.TLabel", background="#172a46", foreground="white", font=("Segoe UI Semibold", 24))
        style.configure("HeaderSub.TLabel", background="#172a46", foreground="#c6d6ee", font=("Segoe UI", 10))
        style.configure("Summary.TLabel", background="#e9f0fb", foreground="#254264", font=("Segoe UI Semibold", 10), padding=(12, 8))
        style.configure("Card.TLabelframe", background="#ffffff", bordercolor="#dbe4f0", relief="solid")
        style.configure("Card.TLabelframe.Label", background="#ffffff", foreground="#1f3654", font=("Segoe UI Semibold", 10))
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("TEntry", fieldbackground="#ffffff", padding=7)
        style.configure("TCombobox", fieldbackground="#ffffff", padding=5)
        style.configure("TSpinbox", fieldbackground="#ffffff", padding=5)
        style.configure("Accent.TButton", background="#2563eb", foreground="white", borderwidth=0, padding=(14, 8), font=("Segoe UI Semibold", 10))
        style.map("Accent.TButton", background=[("active", "#1d4ed8"), ("disabled", "#9db9ef")])
        style.configure("Quiet.TButton", background="#e9f0fb", foreground="#254264", borderwidth=0, padding=(10, 7))
        style.map("Quiet.TButton", background=[("active", "#d7e5f8")])
        style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", foreground="#1f2937", rowheight=28, borderwidth=0)
        style.configure("Treeview.Heading", background="#e9f0fb", foreground="#29415f", font=("Segoe UI Semibold", 9), relief="flat", padding=(8, 7))
        style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", "#123a72")])
        style.configure("Accent.Horizontal.TProgressbar", background="#2563eb", troughcolor="#dce6f5", bordercolor="#dce6f5", thickness=8)

    def _build(self) -> None:
        header = ttk.Frame(self, style="Header.TFrame", padding=(22, 10))
        header.pack(fill=tk.X)
        ttk.Label(header, text="OpenMerger", style="HeaderTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(header, text="Merge large PDF collections locally, safely, and in the order you choose.", style="HeaderSub.TLabel").pack(anchor=tk.W, pady=(2, 0))
        ttk.Button(header, text="PDF toolbox", command=self._open_toolbox, style="Quiet.TButton").pack(side=tk.RIGHT, anchor=tk.N, pady=(4, 0))

        root = ttk.Frame(self, padding=12, style="App.TFrame")
        root.pack(fill=tk.BOTH, expand=True)

        summary = ttk.Label(root, textvariable=self.summary_var, style="Summary.TLabel")
        summary.pack(fill=tk.X, pady=(0, 8))

        source = ttk.LabelFrame(root, text="1. Choose source PDFs", padding=8, style="Card.TLabelframe")
        source.pack(fill=tk.X)
        folder_entry = ttk.Entry(source, textvariable=self.folder_var)
        folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        folder_entry.bind("<Return>", lambda _event: self._scan())
        ttk.Button(source, text="Browse folder", command=self._browse_folder, style="Quiet.TButton").pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(source, text="Add selected PDFs", command=self._add_selected_pdfs, style="Quiet.TButton").pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(source, text="Scan PDFs", command=self._scan, style="Accent.TButton").pack(side=tk.LEFT)

        options = ttk.LabelFrame(root, text="2. Set merge options", padding=8, style="Card.TLabelframe")
        options.pack(fill=tk.X, pady=8)

        ttk.Label(options, text="Sort by").grid(row=0, column=0, sticky=tk.W)
        sort_box = ttk.Combobox(options, textvariable=self.sort_var, values=list(SORT_LABELS), state="readonly", width=22)
        sort_box.grid(row=0, column=1, sticky=tk.W, padx=8)
        sort_box.bind("<<ComboboxSelected>>", lambda _event: self._queue_auto_scan())
        direction_box = ttk.Combobox(options, textvariable=self.direction_var, values=list(DIRECTION_LABELS), state="readonly", width=12)
        direction_box.grid(row=0, column=2, sticky=tk.W, padx=8)
        direction_box.bind("<<ComboboxSelected>>", lambda _event: self._queue_auto_scan())
        ttk.Checkbutton(options, text="Include subfolders", variable=self.recursive_var, command=self._queue_auto_scan).grid(row=0, column=3, sticky=tk.W, padx=8)
        ttk.Checkbutton(options, text="Auto scan folder", variable=self.auto_scan_var, command=self._queue_auto_scan).grid(row=0, column=4, sticky=tk.W, padx=8)

        ttk.Radiobutton(options, text="One merged PDF", variable=self.mode_var, value="single", command=self._update_mode_controls).grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Radiobutton(options, text="Chunk PDFs", variable=self.mode_var, value="chunks", command=self._update_mode_controls).grid(row=1, column=1, sticky=tk.W, pady=(8, 0))
        self.chunk_label = ttk.Label(options, text="PDFs per chunk")
        self.chunk_label.grid(row=1, column=2, sticky=tk.E, padx=(12, 4), pady=(8, 0))
        self.chunk_input = ttk.Spinbox(options, from_=1, to=100000, textvariable=self.chunk_var, width=8)
        self.chunk_input.grid(row=1, column=3, sticky=tk.W, pady=(8, 0))
        ttk.Label(options, text="Internal batch").grid(row=1, column=4, sticky=tk.E, padx=(12, 4), pady=(8, 0))
        ttk.Spinbox(options, from_=2, to=1000, textvariable=self.batch_var, width=6).grid(row=1, column=5, sticky=tk.W, pady=(8, 0))
        ttk.Label(options, text="Workers").grid(row=1, column=6, sticky=tk.E, padx=(12, 4), pady=(8, 0))
        ttk.Spinbox(options, from_=1, to=4, textvariable=self.worker_var, width=5).grid(row=1, column=7, sticky=tk.W, pady=(8, 0))
        ttk.Label(options, text="Compression").grid(row=1, column=8, sticky=tk.E, padx=(12, 4), pady=(8, 0))
        ttk.Combobox(options, textvariable=self.compression_var, values=list(COMPRESSION_LABELS), state="readonly", width=23).grid(row=1, column=9, sticky=tk.W, pady=(8, 0))
        self.resume_check = ttk.Checkbutton(options, text="Resume verified chunks", variable=self.resume_var)
        self.resume_check.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
        ttk.Checkbutton(options, text="Add filename bookmarks", variable=self.bookmark_var).grid(row=2, column=2, columnspan=2, sticky=tk.W, pady=(8, 0))
        ttk.Label(options, text="PDF password").grid(row=2, column=4, sticky=tk.E, padx=(12, 4), pady=(8, 0))
        ttk.Entry(options, textvariable=self.password_var, show="•", width=14).grid(row=2, column=5, sticky=tk.W, pady=(8, 0))
        gs_label = "Ghostscript detected." if ghostscript_available() else "Ghostscript not found: strong compression unavailable."
        ttk.Label(options, text=f"Password is never saved.  {gs_label}").grid(row=2, column=6, columnspan=4, sticky=tk.W, padx=(12, 0), pady=(8, 0))

        output = ttk.LabelFrame(root, text="3. Choose output", padding=8, style="Card.TLabelframe")
        output.pack(fill=tk.X)
        output.columnconfigure(0, weight=1)
        ttk.Entry(output, textvariable=self.output_var).grid(row=0, column=0, sticky=tk.EW, padx=(0, 8))
        ttk.Button(output, text="Output folder", command=self._browse_output_folder, style="Quiet.TButton").grid(row=0, column=1, padx=(0, 6))
        ttk.Button(output, text="Save as", command=self._browse_output, style="Quiet.TButton").grid(row=0, column=2, padx=(0, 6))
        ttk.Button(output, text="Add cover", command=self._browse_cover, style="Quiet.TButton").grid(row=0, column=3, padx=(0, 6))
        ttk.Button(output, text="Save preset", command=self._save_preset, style="Quiet.TButton").grid(row=0, column=4, padx=(0, 6))
        ttk.Button(output, text="Load preset", command=self._load_preset, style="Quiet.TButton").grid(row=0, column=5)
        self.cover_status = ttk.Label(output, text="No cover PDF selected", foreground="#52657d")
        self.cover_status.grid(row=1, column=0, columnspan=6, sticky=tk.W, pady=(5, 0))

        list_frame = ttk.LabelFrame(root, text="4. Review merge order", padding=8, style="Card.TLabelframe")
        toolbar = ttk.Frame(list_frame)
        toolbar.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(toolbar, text="Search").pack(side=tk.LEFT)
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=28)
        self.search_entry.pack(side=tk.LEFT, padx=(6, 12))
        ttk.Button(toolbar, text="Move up", command=lambda: self._move_selected(-1), style="Quiet.TButton").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="Move down", command=lambda: self._move_selected(1), style="Quiet.TButton").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="Remove", command=self._remove_selected, style="Quiet.TButton").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="Keep selected", command=self._keep_selected, style="Quiet.TButton").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="Select visible", command=self._select_visible, style="Quiet.TButton").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="Verify duplicates", command=self._find_duplicates, style="Quiet.TButton").pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Clear list", command=self._clear_files, style="Quiet.TButton").pack(side=tk.LEFT, padx=(6, 0))
        self.page_label = ttk.Label(toolbar, text="")
        self.page_label.pack(side=tk.RIGHT)
        ttk.Button(toolbar, text="Next", command=lambda: self._change_page(1)).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(toolbar, text="Previous", command=lambda: self._change_page(-1)).pack(side=tk.RIGHT)
        columns = ("name", "created", "size", "path")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=4)
        self.tree.heading("name", text="Name")
        self.tree.heading("created", text="Created")
        self.tree.heading("size", text="Size")
        self.tree.heading("path", text="Path")
        self.tree.column("name", width=220)
        self.tree.column("created", width=150)
        self.tree.column("size", width=80, anchor=tk.E)
        self.tree.column("path", width=420)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<ButtonPress-1>", self._start_row_drag)
        self.tree.bind("<ButtonRelease-1>", self._finish_row_drag)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        bottom = ttk.Frame(root)
        bottom.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(bottom, text="Activity log", command=self._open_activity, style="Quiet.TButton").pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(bottom, text="Open output folder", command=self._open_output_folder, style="Quiet.TButton").pack(side=tk.RIGHT, padx=(8, 0))
        self.start_button = ttk.Button(bottom, text="Start merge", command=self._merge, style="Accent.TButton")
        self.start_button.pack(side=tk.RIGHT)
        self.cancel_button = ttk.Button(bottom, text="Cancel", command=self._cancel_merge, state=tk.DISABLED)
        self.cancel_button.pack(side=tk.RIGHT, padx=(8, 0))
        self.pause_button = ttk.Button(bottom, text="Pause", command=self._toggle_pause, state=tk.DISABLED)
        self.pause_button.pack(side=tk.RIGHT)
        ttk.Progressbar(bottom, variable=self.progress_var, maximum=100, style="Accent.Horizontal.TProgressbar").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 12))
        ttk.Label(root, textvariable=self.status_var, foreground="#52657d").pack(fill=tk.X, side=tk.BOTTOM, pady=(8, 0))
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 8))
        self._update_mode_controls()

    def _open_toolbox(self) -> None:
        if self.toolbox_window and self.toolbox_window.winfo_exists():
            self.toolbox_window.deiconify()
            self.toolbox_window.lift()
            self.toolbox_window.focus_force()
            return
        window = tk.Toplevel(self)
        self.toolbox_window = window
        window.title("OpenMerger PDF Toolbox")
        window.geometry("760x590")
        window.minsize(650, 520)
        window.transient(self)
        window.protocol("WM_DELETE_WINDOW", lambda: self._close_toolbox(window))
        frame = ttk.Frame(window, padding=16, style="App.TFrame")
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="PDF Toolbox", font=("Segoe UI Semibold", 18)).grid(row=0, column=0, columnspan=4, sticky=tk.W)
        description = tk.StringVar(value="Choose a local PDF task. Source files are never modified.")
        ttk.Label(frame, textvariable=description, foreground="#52657d").grid(row=1, column=0, columnspan=4, sticky=tk.W, pady=(2, 14))

        operation = tk.StringVar(value="Extract / rotate pages")
        source = tk.StringVar()
        output = tk.StringVar(value=str(Path.home() / "Desktop" / "output.pdf"))
        pages = tk.StringVar()
        rotation = tk.IntVar(value=0)
        split_count = tk.IntVar(value=25)
        password = tk.StringVar()
        owner_password = tk.StringVar()
        title = tk.StringVar()
        author = tk.StringVar()
        subject = tk.StringVar()
        image_preset = tk.StringVar(value="Print A4")
        image_fit = tk.StringVar(value="Fit with margins")
        image_margin = tk.DoubleVar(value=8)
        image_dpi = tk.IntVar(value=150)

        labels = [
            "Extract / rotate pages",
            "Split PDF",
            "Images to PDF",
            "Protect PDF",
            "Unlock PDF",
            "Edit metadata",
            "Inspect image metadata",
            "Remove image metadata",
            "Add page numbers",
            "Add text watermark",
            "Create cover page",
            "Export PDF pages to PNG",
            "Remove blank pages",
            "Find duplicate pages",
            "PDF to DOCX",
            "DOCX to PDF",
            "Excel to CSV",
            "CSV to Excel",
            "PDF to PPTX",
            "PPTX to PDF",
        ]
        ttk.Label(frame, text="Task").grid(row=2, column=0, sticky=tk.W)
        task_box = ttk.Combobox(frame, textvariable=operation, values=labels, state="readonly", width=28)
        task_box.grid(row=2, column=1, sticky=tk.W, padx=(8, 0))

        ttk.Label(frame, text="Source").grid(row=3, column=0, sticky=tk.W, pady=(10, 0))
        ttk.Entry(frame, textvariable=source).grid(row=3, column=1, columnspan=2, sticky=tk.EW, padx=8, pady=(10, 0))

        def choose_source() -> None:
            if operation.get() in {"Images to PDF", "Inspect image metadata", "Remove image metadata"}:
                if operation.get() in {"Images to PDF", "Inspect image metadata"}:
                    selected = filedialog.askopenfilenames(
                        parent=window,
                        title="Choose images" if operation.get() == "Images to PDF" else "Choose images to inspect",
                        filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp")],
                    )
                    if selected:
                        source.set("|".join(selected))
                    return
                selected = filedialog.askopenfilename(parent=window, title="Choose an image", filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp")])
                if selected:
                    source.set(selected)
            else:
                selected = filedialog.askopenfilename(parent=window, title="Choose PDF", filetypes=[("PDF files", "*.pdf")])
                if selected:
                    source.set(selected)

        ttk.Button(frame, text="Choose input", command=choose_source, style="Quiet.TButton").grid(row=3, column=3, pady=(10, 0))
        ttk.Label(frame, text="Output").grid(row=4, column=0, sticky=tk.W, pady=(10, 0))
        ttk.Entry(frame, textvariable=output).grid(row=4, column=1, columnspan=2, sticky=tk.EW, padx=8, pady=(10, 0))
        ttk.Button(frame, text="Save as", command=lambda: self._choose_tool_output(output, window, operation.get()), style="Quiet.TButton").grid(row=4, column=3, pady=(10, 0))

        ttk.Label(frame, text="Pages").grid(row=5, column=0, sticky=tk.W, pady=(10, 0))
        ttk.Entry(frame, textvariable=pages, width=26).grid(row=5, column=1, sticky=tk.W, padx=8, pady=(10, 0))
        ttk.Label(frame, text="Example: 1-3,5,8-").grid(row=5, column=2, columnspan=2, sticky=tk.W, pady=(10, 0))
        ttk.Label(frame, text="Rotate").grid(row=6, column=0, sticky=tk.W, pady=(10, 0))
        ttk.Combobox(frame, textvariable=rotation, values=(0, 90, 180, 270), state="readonly", width=8).grid(row=6, column=1, sticky=tk.W, padx=8, pady=(10, 0))
        ttk.Label(frame, text="Split every").grid(row=6, column=2, sticky=tk.E, pady=(10, 0))
        ttk.Spinbox(frame, from_=1, to=100000, textvariable=split_count, width=8).grid(row=6, column=3, sticky=tk.W, pady=(10, 0))
        ttk.Label(frame, text="Password").grid(row=7, column=0, sticky=tk.W, pady=(10, 0))
        ttk.Entry(frame, textvariable=password, show="•", width=26).grid(row=7, column=1, sticky=tk.W, padx=8, pady=(10, 0))
        ttk.Label(frame, text="Owner password").grid(row=7, column=2, sticky=tk.E, pady=(10, 0))
        ttk.Entry(frame, textvariable=owner_password, show="•", width=18).grid(row=7, column=3, sticky=tk.W, pady=(10, 0))
        ttk.Label(frame, text="Title / watermark").grid(row=8, column=0, sticky=tk.W, pady=(10, 0))
        ttk.Entry(frame, textvariable=title).grid(row=8, column=1, sticky=tk.EW, padx=8, pady=(10, 0))
        ttk.Label(frame, text="Author").grid(row=8, column=2, sticky=tk.E, pady=(10, 0))
        ttk.Entry(frame, textvariable=author, width=18).grid(row=8, column=3, sticky=tk.W, pady=(10, 0))
        ttk.Label(frame, text="Subject / cover subtitle").grid(row=9, column=0, sticky=tk.W, pady=(10, 0))
        ttk.Entry(frame, textvariable=subject).grid(row=9, column=1, columnspan=3, sticky=tk.EW, padx=8, pady=(10, 0))
        ttk.Label(frame, text="Image layout").grid(row=10, column=0, sticky=tk.W, pady=(10, 0))
        ttk.Combobox(frame, textvariable=image_preset, values=("Original size", "Print A4", "US Letter", "Poster", "Social portrait", "Wide banner"), state="readonly", width=18).grid(row=10, column=1, sticky=tk.W, padx=8, pady=(10, 0))
        ttk.Combobox(frame, textvariable=image_fit, values=("Fit with margins", "Fill and crop"), state="readonly", width=17).grid(row=10, column=2, sticky=tk.W, pady=(10, 0))
        ttk.Spinbox(frame, from_=0, to=30, increment=1, textvariable=image_margin, width=5).grid(row=10, column=3, sticky=tk.W, pady=(10, 0))
        ttk.Label(frame, text="Margin mm  •  150 DPI is best for screen; 300 DPI for print.").grid(row=11, column=0, columnspan=3, sticky=tk.W, pady=(6, 0))
        ttk.Combobox(frame, textvariable=image_dpi, values=(150, 300), state="readonly", width=5).grid(row=11, column=3, sticky=tk.W, pady=(6, 0))
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)

        def update_help(*_args: object) -> None:
            messages = {
                "Extract / rotate pages": "Extract page ranges or rotate all selected pages. Leave Pages blank for every page.",
                "Split PDF": "Create several PDFs with the chosen number of pages in each output.",
                "Images to PDF": "Choose one or more images and create one PDF in the same order.",
                "Protect PDF": "Create a password-protected copy. Password fields are never saved.",
                "Unlock PDF": "Remove protection from a PDF when you know its current password.",
                "Edit metadata": "Create a copy with a title, author, and subject.",
                "Inspect image metadata": "Show image dimensions, camera/EXIF, GPS, copyright, and other embedded details locally.",
                "Remove image metadata": "Create an image copy without EXIF, GPS, XMP, and other embedded metadata.",
                "Add page numbers": "Add a subtle page number footer to every page in a new PDF.",
                "Add text watermark": "Add centered watermark text to every page in a new PDF.",
                "Create cover page": "Create a new PDF cover page from the Title and Subject fields.",
                "Export PDF pages to PNG": "Render every PDF page as a high-quality PNG image in the output folder.",
                "Remove blank pages": "Detect near-empty white pages and create a cleaned PDF copy without them.",
                "Find duplicate pages": "Find visually identical pages by comparing local low-resolution renderings.",
                "PDF to DOCX": "Extract selectable PDF text into an editable Word document; scanned PDFs need OCR first.",
                "DOCX to PDF": "Convert Word files with the bundled Full-edition engine or an installed LibreOffice.",
                "Excel to CSV": "Export the active Excel worksheet to a UTF-8 CSV file.",
                "CSV to Excel": "Create an XLSX workbook from a CSV file.",
                "PDF to PPTX": "Create a PowerPoint with one rendered PDF page per slide.",
                "PPTX to PDF": "Convert PowerPoint files with the bundled Full-edition engine or an installed LibreOffice.",
            }
            description.set(messages[operation.get()])
            if Path(output.get()).name.startswith("output."):
                extension = TOOL_OUTPUT_SPECS.get(operation.get(), (".pdf", "PDF files", "*.pdf"))[0]
                output.set(str(Path.home() / "Desktop" / f"output{extension}"))

        task_box.bind("<<ComboboxSelected>>", update_help)

        def run_tool() -> None:
            values = {
                "operation": operation.get(), "source": source.get(), "output": output.get(), "pages": pages.get(),
                "rotation": rotation.get(), "split": split_count.get(), "password": password.get(), "owner": owner_password.get(),
                "title": title.get(), "author": author.get(), "subject": subject.get(), "image_preset": image_preset.get(),
                "image_fit": image_fit.get(), "image_margin": image_margin.get(), "image_dpi": image_dpi.get(),
            }
            needs_source = values["operation"] not in {"Inspect image metadata", "Create cover page"}
            needs_output = values["operation"] not in {"Inspect image metadata", "Find duplicate pages"}
            if (needs_source and not values["source"]) or (needs_output and not values["output"]):
                messagebox.showwarning("PDF toolbox", "Choose an input and, when required, an output file first.")
                return
            threading.Thread(target=self._tool_worker, args=(values,), daemon=True).start()

        ttk.Button(frame, text="Run tool", command=run_tool, style="Accent.TButton").grid(row=12, column=3, sticky=tk.E, pady=(18, 0))

    def _close_toolbox(self, window: tk.Toplevel) -> None:
        if window.winfo_exists():
            window.destroy()
        self.toolbox_window = None

    def _choose_tool_output(self, variable: tk.StringVar, parent: tk.Misc | None = None, operation: str = "") -> None:
        if operation == "Remove image metadata":
            path = filedialog.asksaveasfilename(parent=parent, title="Save metadata-free image as", defaultextension=".png", filetypes=[("PNG image", "*.png"), ("JPEG image", "*.jpg"), ("WebP image", "*.webp"), ("TIFF image", "*.tiff")])
        elif operation in TOOL_OUTPUT_SPECS:
            extension, label, pattern = TOOL_OUTPUT_SPECS[operation]
            path = filedialog.asksaveasfilename(parent=parent, title=f"Save {label} as", defaultextension=extension, filetypes=[(label, pattern)])
        else:
            path = filedialog.asksaveasfilename(parent=parent, title="Save PDF as", defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")])
        if path:
            variable.set(path)

    def _show_metadata_report(self, report: str) -> None:
        window = tk.Toplevel(self)
        window.title("Image metadata report")
        window.geometry("720x520")
        frame = ttk.Frame(window, padding=12, style="App.TFrame")
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Image metadata report", font=("Segoe UI Semibold", 14)).pack(anchor=tk.W)
        ttk.Label(frame, text="One JSON report for every selected image. Review GPS or camera details before sharing.", foreground="#52657d").pack(anchor=tk.W, pady=(2, 8))

        def save_json() -> None:
            path = filedialog.asksaveasfilename(parent=window, title="Save metadata report", defaultextension=".json", initialfile="image_metadata.json", filetypes=[("JSON files", "*.json")])
            if path:
                Path(path).write_text(report, encoding="utf-8")
                self._log(f"Saved image metadata report: {path}")

        ttk.Button(frame, text="Save JSON", command=save_json, style="Accent.TButton").pack(anchor=tk.E, pady=(0, 8))
        text_box = tk.Text(frame, wrap=tk.WORD, background="#ffffff", foreground="#172033", relief=tk.FLAT)
        text_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text_box.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text_box.configure(yscrollcommand=scroll.set)
        text_box.insert(tk.END, report)
        text_box.configure(state=tk.DISABLED)

    def _tool_worker(self, values: dict[str, object]) -> None:
        try:
            operation = str(values["operation"])
            output = Path(str(values["output"])).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            password = str(values["password"]) or None
            if operation == "Images to PDF":
                presets = {
                    "Original size": "original", "Print A4": "a4", "US Letter": "letter", "Poster": "poster",
                    "Social portrait": "social", "Wide banner": "banner",
                }
                count = images_to_pdf(
                    [Path(path) for path in str(values["source"]).split("|")], output,
                    presets[str(values["image_preset"])], "contain" if values["image_fit"] == "Fit with margins" else "cover",
                    float(values["image_margin"]), int(values["image_dpi"]),
                )
                message = f"Created {output.name} from {count} image(s)."
            elif operation == "Inspect image metadata":
                paths = [Path(path).expanduser().resolve() for path in str(values["source"]).split("|")]
                self.events.put(("metadata_report", image_metadata_reports(paths)))
                return
            elif operation == "Remove image metadata":
                remove_image_metadata(Path(str(values["source"])).expanduser().resolve(), output)
                message = f"Created metadata-free image: {output.name}."
            elif operation == "Create cover page":
                create_cover_page(output, str(values["title"]), str(values["subject"]))
                message = f"Created cover page: {output.name}."
            else:
                source = Path(str(values["source"])).expanduser().resolve()
                if operation == "Extract / rotate pages":
                    count = transform_pdf(source, output, str(values["pages"]) or None, int(values["rotation"]), password)
                    message = f"Created {output.name} with {count} page(s)."
                elif operation == "Split PDF":
                    outputs = split_pdf(source, output, int(values["split"]), password)
                    message = f"Created {len(outputs)} split PDF(s)."
                elif operation == "Protect PDF":
                    protect_pdf(source, output, str(values["password"]), str(values["owner"]) or None)
                    message = f"Created protected PDF: {output.name}."
                elif operation == "Unlock PDF":
                    unlock_pdf(source, output, str(values["password"]))
                    message = f"Created unlocked PDF: {output.name}."
                elif operation == "Add page numbers":
                    add_page_numbers(source, output, password=password)
                    message = f"Created numbered PDF: {output.name}."
                elif operation == "Add text watermark":
                    add_text_watermark(source, output, str(values["title"]), password=password)
                    message = f"Created watermarked PDF: {output.name}."
                elif operation == "Export PDF pages to PNG":
                    images = pdf_to_images(source, output.parent, "png", int(values["image_dpi"]), password)
                    message = f"Exported {len(images)} page image(s) to {output.parent}."
                elif operation == "Remove blank pages":
                    removed = remove_blank_pages(source, output, password=password)
                    message = f"Created cleaned PDF; removed {len(removed)} blank page(s): {removed or 'none'}."
                elif operation == "Find duplicate pages":
                    groups = find_duplicate_pages(source, password)
                    message = f"Duplicate page groups: {groups}" if groups else "No visually identical pages found."
                elif operation == "PDF to DOCX":
                    message = f"Created DOCX with text from {pdf_to_docx(source, output, password)} page(s)."
                elif operation == "PDF to PPTX":
                    message = f"Created PPTX with {pdf_to_pptx(source, output, password=password)} slide(s)."
                elif operation == "Excel to CSV":
                    message = f"Created CSV with {excel_to_csv(source, output)} row(s)."
                elif operation == "CSV to Excel":
                    message = f"Created Excel workbook with {csv_to_excel(source, output)} row(s)."
                elif operation in {"DOCX to PDF", "PPTX to PDF"}:
                    office_to_pdf(source, output)
                    message = f"Created PDF: {output.name}."
                else:
                    update_metadata(source, output, str(values["title"]), str(values["author"]), str(values["subject"]), password)
                    message = f"Updated metadata in {output.name}."
            self.events.put(("tool_complete", message))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _browse_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose folder containing PDFs")
        if folder:
            self.folder_var.set(folder)
            self._queue_auto_scan(delay_ms=100)

    def _add_selected_pdfs(self) -> None:
        selected = filedialog.askopenfilenames(
            title="Choose PDFs to merge",
            filetypes=[("PDF files", "*.pdf")],
        )
        if not selected:
            return
        existing = {item.path.resolve() for item in self.files}
        added: list[PdfInfo] = []
        skipped = 0
        for raw_path in selected:
            path = Path(raw_path).expanduser().resolve()
            if path in existing:
                skipped += 1
                continue
            try:
                stat = path.stat()
            except OSError:
                skipped += 1
                continue
            added.append(PdfInfo(path, path.name, stat.st_size, stat.st_ctime, stat.st_mtime, ()))
            existing.add(path)
        if not added:
            messagebox.showinfo("No PDFs added", "Those PDF files are already in the merge list or cannot be read.")
            return
        self.files.extend(added)
        self.page_index = 0
        self._refresh_tree()
        total_size = format_size(sum(item.size for item in self.files))
        detail = f" ({skipped} skipped)" if skipped else ""
        self.summary_var.set(f"{len(self.files):,} PDFs ready to merge  •  {total_size} total  •  {self._estimate_output_count()} output file(s)")
        self.status_var.set(f"Added {len(added)} selected PDF(s){detail}. Drag rows to set their order.")
        self._log(f"Added {len(added)} selected PDF(s){detail}.")

    def _browse_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save merged PDF as",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile="merged.pdf",
        )
        if path:
            self.output_var.set(path)

    def _browse_output_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            self.output_var.set(str(Path(folder) / "merged.pdf"))

    def _browse_cover(self) -> None:
        path = filedialog.askopenfilename(title="Optional cover PDF", filetypes=[("PDF files", "*.pdf")])
        if path:
            self.cover_var.set(path)
            self._update_cover_status()
            self._log(f"Cover PDF selected: {Path(path).name}")

    def _update_mode_controls(self) -> None:
        if self.mode_var.get() == "chunks":
            self.chunk_label.grid()
            self.chunk_input.grid()
            self.resume_check.grid()
        else:
            self.chunk_label.grid_remove()
            self.chunk_input.grid_remove()
            self.resume_check.grid_remove()

    def _update_cover_status(self) -> None:
        cover = self.cover_var.get().strip()
        self.cover_status.configure(text=f"Cover PDF: {Path(cover).name}" if cover else "No cover PDF selected")

    def _scan(self) -> None:
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showwarning("Folder required", "Please choose or paste a folder path.")
            return
        if not Path(folder).expanduser().is_dir():
            messagebox.showwarning("Folder not found", "The folder path does not exist.")
            return
        self.status_var.set("Scanning PDFs...")
        self.summary_var.set("Scanning folder…")
        self._log("Scanning PDFs...")
        self._scan_generation += 1
        sort_mode = SORT_LABELS[self.sort_var.get()]
        sort_direction = DIRECTION_LABELS[self.direction_var.get()]
        recursive = self.recursive_var.get()
        threading.Thread(target=self._scan_worker, args=(folder, self._scan_generation, sort_mode, sort_direction, recursive), daemon=True).start()

    def _queue_auto_scan(self, *_args: object, delay_ms: int = 700) -> None:
        if self._auto_scan_after:
            self.after_cancel(self._auto_scan_after)
            self._auto_scan_after = None
        if not self.auto_scan_var.get():
            return
        folder = self.folder_var.get().strip()
        if not folder or not Path(folder).expanduser().is_dir():
            return
        self._auto_scan_after = self.after(delay_ms, self._scan)

    def _scan_worker(self, folder: str, generation: int, sort_mode: str, sort_direction: str, recursive: bool) -> None:
        try:
            files = scan_folder(folder, recursive, sort_mode, sort_direction)
            self.events.put(("scan_complete", (generation, files)))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _merge(self) -> None:
        if not self.files:
            messagebox.showwarning("No PDFs", "Scan a folder first.")
            return
        if self._merge_thread and self._merge_thread.is_alive():
            messagebox.showwarning("Merge running", "A merge is already running.")
            return
        output = self.output_var.get().strip()
        if not output:
            messagebox.showwarning("Output required", "Choose an output PDF path.")
            return
        output_folder = Path(output).expanduser().resolve().parent
        output_folder.mkdir(parents=True, exist_ok=True)
        total_size = sum(item.size for item in self.files)
        free_space = shutil.disk_usage(output_folder).free
        if free_space < total_size * 2:
            if not messagebox.askyesno(
                "Low disk space",
                "Free disk space may be low for this merge.\n\nContinue anyway?",
            ):
                return
        estimate = self._estimate_output_count()
        if not messagebox.askyesno("Start merge", f"Ready to merge {len(self.files)} PDF(s) into {estimate} output file(s)?"):
            return
        self.status_var.set("Merging started...")
        self._log(f"Merging {len(self.files)} PDF(s) into {estimate} output file(s).")
        self.progress_var.set(0)
        self._stop_event.clear()
        self._pause_event.clear()
        self.start_button.configure(state=tk.DISABLED)
        self.pause_button.configure(state=tk.NORMAL, text="Pause")
        self.cancel_button.configure(state=tk.NORMAL)
        merge_files = list(self.files)
        cover = self.cover_var.get().strip()
        if cover:
            cover_path = Path(cover).expanduser().resolve()
            if not cover_path.is_file() or cover_path.suffix.casefold() != ".pdf":
                messagebox.showwarning("Cover PDF", "Choose a valid cover PDF.")
                return
            if cover_path not in {item.path for item in merge_files}:
                stat = cover_path.stat()
                merge_files.insert(0, PdfInfo(cover_path, cover_path.name, stat.st_size, stat.st_ctime, stat.st_mtime, ()))
        settings = {
            "files": merge_files,
            "mode": "chunks" if self.mode_var.get() == "chunks" else "single",
            "chunk_size": int(self.chunk_var.get()),
            "batch_size": int(self.batch_var.get()),
            "workers": int(self.worker_var.get()),
            "compression": COMPRESSION_LABELS[self.compression_var.get()],
            "skip_existing": self.resume_var.get() and self.mode_var.get() == "chunks",
            "bookmarks": self.bookmark_var.get(),
            "password": self.password_var.get() or None,
        }
        self._merge_thread = threading.Thread(target=self._merge_worker, args=(output, settings), daemon=True)
        self._merge_thread.start()

    def _merge_worker(self, output: str, settings: dict[str, object]) -> None:
        try:
            def progress(done: int, total: int, message: str) -> None:
                percent = min(100, round((done / total) * 100, 2))
                self.events.put(("progress", (percent, message)))

            result = merge_collection(
                settings["files"],
                output,
                settings["mode"],
                settings["chunk_size"],
                settings["batch_size"],
                settings["workers"],
                settings["compression"],
                settings["skip_existing"],
                self._stop_event,
                self._pause_event,
                progress,
                settings["bookmarks"],
                settings["password"],
            )
            self.events.put(("merge_complete", result))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _drain_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "scan_complete":
                    generation, files = payload
                    if generation == self._scan_generation:
                        self._show_files(files)
                elif event == "progress":
                    percent, message = payload
                    self.progress_var.set(percent)
                    self.status_var.set(str(message))
                    self._log(str(message))
                elif event == "merge_complete":
                    result: MergeResult = payload
                    outputs = result.outputs
                    self.progress_var.set(0 if result.cancelled else 100)
                    self._set_merge_buttons_idle()
                    if result.cancelled:
                        self.status_var.set("Merge cancelled. Completed chunk outputs can be safely resumed.")
                        self._log("Merge cancelled. Resume uses the saved job manifest.")
                        messagebox.showinfo("Merge cancelled", "The merge was cancelled. Completed chunks were preserved and can be safely resumed.")
                        continue
                    failure_text = f" Skipped {len(result.failures)} failed PDF(s)." if result.failures else ""
                    report_text = f"\nFailure report: {result.report_path}" if result.report_path else ""
                    self.status_var.set(f"Done. Created {len(outputs)} PDF file(s).{failure_text}")
                    self._log(f"Done. Created {len(outputs)} PDF file(s).{failure_text}")
                    self._record_recent_job(outputs)
                    messagebox.showinfo("Merge complete", f"Created {len(outputs)} PDF file(s).{failure_text}{report_text}")
                elif event == "duplicates_complete":
                    groups, report = payload
                    count = sum(len(group) for group in groups)
                    if not groups:
                        messagebox.showinfo("Duplicates", "No byte-identical duplicate PDFs found.")
                        self._log("No byte-identical duplicate PDFs found.")
                        continue
                    lines = ["Verified duplicate PDFs", "=======================", ""]
                    for group in groups:
                        lines.extend(str(item.path) for item in group)
                        lines.append("")
                    report.write_text("\n".join(lines), encoding="utf-8")
                    self._log(f"Found {count} verified duplicate(s). Report: {report}")
                    messagebox.showinfo("Duplicates", f"Found {count} verified duplicate(s).\nReport saved:\n{report}")
                elif event == "tool_complete":
                    message = str(payload)
                    self.status_var.set(message)
                    self._log(message)
                    messagebox.showinfo("PDF toolbox", message)
                elif event == "metadata_report":
                    self._show_metadata_report(str(payload))
                elif event == "error":
                    self._set_merge_buttons_idle()
                    self.status_var.set("Error")
                    self._log(f"Error: {payload}")
                    messagebox.showerror("OpenMerger", str(payload))
        except queue.Empty:
            pass
        self.after(150, self._drain_events)

    def _show_files(self, files: list[PdfInfo]) -> None:
        self.files = files
        self.page_index = 0
        self._refresh_tree()
        total_size = format_size(sum(item.size for item in files))
        shown = " Showing first 10,000 rows." if len(files) > 10000 else ""
        chunks = self._estimate_output_count()
        self.status_var.set(f"Found {len(files)} PDF(s), total {total_size}, output {chunks} file(s).{shown}")
        self.summary_var.set(f"{len(files):,} PDFs ready to merge  •  {total_size} total  •  {chunks} output file(s)")
        self._log(f"Found {len(files)} PDF(s), total {total_size}, output {chunks} file(s).")

    def _refresh_tree(self) -> None:
        query = self.search_var.get().strip().casefold()
        matches = [index for index, item in enumerate(self.files) if not query or query in item.name.casefold() or query in str(item.path).casefold()]
        max_page = max(0, (len(matches) - 1) // self.page_size)
        self.page_index = min(self.page_index, max_page)
        start = self.page_index * self.page_size
        self.visible_indexes = matches[start : start + self.page_size]
        self.visible_files = [self.files[index] for index in self.visible_indexes]
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self.visible_files):
            self.tree.insert("", tk.END, iid=str(index), values=(item.name, item.created_label, item.size_label, str(item.path)))
        page_count = max(1, max_page + 1)
        self.page_label.configure(text=f"{len(matches):,} match(es) · page {self.page_index + 1}/{page_count}")

    def _queue_refresh(self, *_args: object) -> None:
        if self._refresh_after:
            self.after_cancel(self._refresh_after)
        self._refresh_after = self.after(200, self._refresh_tree)

    def _focus_search(self, _event: object | None = None) -> str:
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, tk.END)
        return "break"

    def _start_row_drag(self, event: tk.Event[tk.Misc]) -> None:
        row = self.tree.identify_row(event.y)
        self._drag_item = row or None

    def _finish_row_drag(self, event: tk.Event[tk.Misc]) -> None:
        source_id = self._drag_item
        self._drag_item = None
        target_id = self.tree.identify_row(event.y)
        if not source_id or not target_id or source_id == target_id:
            return
        try:
            source_index = self.visible_indexes[int(source_id)]
            target_index = self.visible_indexes[int(target_id)]
        except (IndexError, ValueError):
            return
        item = self.files.pop(source_index)
        if source_index < target_index:
            target_index -= 1
        self.files.insert(target_index, item)
        self._refresh_tree()
        self._log("Manual order updated by drag and drop.")

    def _change_page(self, direction: int) -> None:
        self.page_index = max(0, self.page_index + direction)
        self._refresh_tree()

    def _selected_file_indexes(self) -> list[int]:
        indexes: list[int] = []
        for item_id in self.tree.selection():
            try:
                indexes.append(self.visible_indexes[int(item_id)])
            except (IndexError, ValueError):
                continue
        return sorted(set(indexes))

    def _move_selected(self, direction: int) -> None:
        indexes = self._selected_file_indexes()
        if not indexes:
            return
        if direction < 0:
            iterable = indexes
        else:
            iterable = reversed(indexes)
        for index in iterable:
            new_index = index + direction
            if 0 <= new_index < len(self.files):
                self.files[index], self.files[new_index] = self.files[new_index], self.files[index]
        self._refresh_tree()
        self._log("Manual order updated.")

    def _remove_selected(self) -> None:
        indexes = self._selected_file_indexes()
        if not indexes:
            return
        for index in reversed(indexes):
            del self.files[index]
        self._refresh_tree()
        self.summary_var.set(f"{len(self.files):,} PDFs remain in the merge list")
        self._log(f"Removed {len(indexes)} PDF(s) from merge list.")

    def _keep_selected(self) -> None:
        indexes = self._selected_file_indexes()
        if not indexes:
            messagebox.showinfo("Select PDFs", "Select the PDFs to merge first. Hold Ctrl while clicking to select more than one.")
            return
        selected = set(indexes)
        removed = len(self.files) - len(selected)
        self.files = [item for index, item in enumerate(self.files) if index in selected]
        self.page_index = 0
        self._refresh_tree()
        self.summary_var.set(f"{len(self.files):,} selected PDF(s) ready to merge")
        self.status_var.set(f"Keeping {len(self.files)} selected PDF(s); removed {removed} from this merge job.")
        self._log(f"Kept {len(self.files)} selected PDF(s); removed {removed} from merge list.")

    def _select_visible(self) -> None:
        self.tree.selection_set(self.tree.get_children())

    def _clear_files(self) -> None:
        if not self.files:
            return
        if not messagebox.askyesno("Clear merge list", "Remove all scanned PDFs from the current merge list?"):
            return
        self.files = []
        self.visible_files = []
        self.visible_indexes = []
        self._refresh_tree()
        self.summary_var.set("No PDFs loaded yet")
        self.status_var.set("Merge list cleared. Choose a folder to begin.")
        self._log("Cleared the merge list.")

    def _find_duplicates(self) -> None:
        seen: dict[tuple[str, int], list[PdfInfo]] = {}
        for item in self.files:
            seen.setdefault((item.name.casefold(), item.size), []).append(item)
        candidates = [group for group in seen.values() if len(group) > 1]
        if not candidates:
            messagebox.showinfo("Duplicates", "No same-name and same-size duplicates found.")
            return
        report = Path(self.output_var.get()).expanduser().resolve().parent / "duplicate_pdfs.txt"
        self._log(f"Verifying {sum(len(group) for group in candidates)} duplicate candidate(s) with SHA-256...")
        threading.Thread(target=self._duplicate_worker, args=(candidates, report), daemon=True).start()

    def _duplicate_worker(self, candidates: list[list[PdfInfo]], report: Path) -> None:
        try:
            verified: list[list[PdfInfo]] = []
            for group in candidates:
                by_hash: dict[str, list[PdfInfo]] = {}
                for item in group:
                    digest = hashlib.sha256()
                    with item.path.open("rb") as handle:
                        for block in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(block)
                    by_hash.setdefault(digest.hexdigest(), []).append(item)
                verified.extend(group for group in by_hash.values() if len(group) > 1)
            self.events.put(("duplicates_complete", (verified, report)))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _toggle_pause(self) -> None:
        if self._pause_event.is_set():
            self._pause_event.clear()
            self.pause_button.configure(text="Pause")
            self._log("Merge resumed.")
        else:
            self._pause_event.set()
            self.pause_button.configure(text="Resume")
            self._log("Merge paused.")

    def _cancel_merge(self) -> None:
        self._stop_event.set()
        self._pause_event.clear()
        self._log("Cancel requested. Waiting for current batch to stop...")

    def _set_merge_buttons_idle(self) -> None:
        self.start_button.configure(state=tk.NORMAL)
        self.pause_button.configure(state=tk.DISABLED, text="Pause")
        self.cancel_button.configure(state=tk.DISABLED)

    def _open_output_folder(self) -> None:
        folder = Path(self.output_var.get()).expanduser().resolve().parent
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def _estimate_output_count(self) -> int:
        if self.mode_var.get() != "chunks":
            return 1 if self.files else 0
        chunk_size = max(1, int(self.chunk_var.get()))
        return (len(self.files) + chunk_size - 1) // chunk_size

    def _log(self, message: str) -> None:
        self.log_messages.append(message)
        if self.log_box and self.log_box.winfo_exists():
            self.log_box.insert(tk.END, f"{message}\n")
            self.log_box.see(tk.END)

    def _open_activity(self) -> None:
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.deiconify()
            self.log_window.lift()
            return
        window = tk.Toplevel(self)
        window.title("OpenMerger activity")
        window.geometry("760x340")
        window.minsize(480, 220)
        frame = ttk.Frame(window, padding=12, style="App.TFrame")
        frame.pack(fill=tk.BOTH, expand=True)
        text_box = tk.Text(frame, wrap=tk.WORD, background="#ffffff", foreground="#172033", relief=tk.FLAT)
        text_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text_box.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_box.configure(yscrollcommand=scrollbar.set)
        text_box.insert(tk.END, "\n".join(self.log_messages) + ("\n" if self.log_messages else "No activity yet.\n"))
        text_box.see(tk.END)
        self.log_window = window
        self.log_box = text_box

    def _settings_payload(self) -> dict[str, object]:
        return {
            "folder": self.folder_var.get(),
            "output": self.output_var.get(),
            "sort": self.sort_var.get(),
            "direction": self.direction_var.get(),
            "compression": self.compression_var.get(),
            "recursive": self.recursive_var.get(),
            "mode": self.mode_var.get(),
            "chunk_size": self.chunk_var.get(),
            "batch_size": self.batch_var.get(),
            "workers": self.worker_var.get(),
            "resume": self.resume_var.get(),
            "bookmarks": self.bookmark_var.get(),
            "cover": self.cover_var.get(),
        }

    def _save_preset(self) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        previous = self._read_settings()
        previous["preset"] = self._settings_payload()
        self.settings_path.write_text(json.dumps(previous, indent=2), encoding="utf-8")
        self._log("Preset saved.")

    def _load_preset(self) -> None:
        preset = self._read_settings().get("preset")
        if not isinstance(preset, dict):
            messagebox.showinfo("OpenMerger", "No saved preset yet.")
            return
        string_vars = {"folder": self.folder_var, "output": self.output_var, "sort": self.sort_var, "direction": self.direction_var, "compression": self.compression_var, "mode": self.mode_var, "cover": self.cover_var}
        bool_vars = {"recursive": self.recursive_var, "resume": self.resume_var, "bookmarks": self.bookmark_var}
        int_vars = {"chunk_size": self.chunk_var, "batch_size": self.batch_var, "workers": self.worker_var}
        for key, variable in string_vars.items():
            if key in preset:
                variable.set(str(preset[key]))
        for key, variable in bool_vars.items():
            if key in preset:
                variable.set(bool(preset[key]))
        for key, variable in int_vars.items():
            if key in preset:
                variable.set(int(preset[key]))
        self._update_mode_controls()
        self._update_cover_status()
        self._log("Preset loaded.")

    def _record_recent_job(self, outputs: list[Path]) -> None:
        data = self._read_settings()
        recent = data.get("recent_jobs", [])
        if not isinstance(recent, list):
            recent = []
        recent.insert(0, {"settings": self._settings_payload(), "outputs": [str(path) for path in outputs]})
        data["recent_jobs"] = recent[:10]
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _read_settings(self) -> dict[str, object]:
        try:
            value = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}


def main() -> None:
    app = PdfMergerApp()
    app.mainloop()
