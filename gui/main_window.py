import tkinter as tk
from pathlib import Path
from threading import Thread
from tkinter import filedialog, ttk
from typing import Callable

from browser.novelpia_client import NovelInfo


class MainWindow(tk.Tk):
    def __init__(
        self,
        on_search: Callable[[str, str], list[NovelInfo]],
        on_download: Callable[[str, str, Path, Callable], None],
    ):
        super().__init__()
        self._on_search = on_search
        self._on_download = on_download
        self._novels: list[NovelInfo] = []
        self.title("노벨피아 다운로더")
        self.geometry("520x540")
        self._build()

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)

        # Search row
        search_frame = ttk.Frame(frame)
        search_frame.pack(fill="x", pady=(0, 6))
        self._search_type = tk.StringVar(value="title")
        ttk.Combobox(
            search_frame,
            textvariable=self._search_type,
            values=["title", "author", "tag"],
            width=8,
            state="readonly",
        ).pack(side="left", padx=(0, 4))
        self._search_entry = ttk.Entry(search_frame)
        self._search_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(search_frame, text="검색", command=self._do_search).pack(side="left")
        self._search_entry.bind("<Return>", lambda _: self._do_search())

        # Results list with scrollbar
        list_frame = ttk.LabelFrame(frame, text="검색 결과", padding=4)
        list_frame.pack(fill="both", expand=True, pady=(0, 6))
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        self._listbox = tk.Listbox(list_frame, height=12, yscrollcommand=scrollbar.set)
        self._listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self._listbox.yview)
        self._listbox.bind("<<ListboxSelect>>", self._on_select)

        # Output folder selector
        folder_frame = ttk.Frame(frame)
        folder_frame.pack(fill="x", pady=(0, 6))
        ttk.Label(folder_frame, text="저장 폴더:").pack(side="left")
        self._folder_var = tk.StringVar(value=str(Path.home() / "novels"))
        ttk.Entry(folder_frame, textvariable=self._folder_var, width=30).pack(side="left", padx=4)
        ttk.Button(folder_frame, text="변경", command=self._choose_folder).pack(side="left")

        # Download button
        self._dl_btn = ttk.Button(
            frame, text="다운로드 시작", command=self._start_download, state="disabled"
        )
        self._dl_btn.pack(pady=(0, 6))

        # Progress section
        prog_frame = ttk.LabelFrame(frame, text="진행 상황", padding=6)
        prog_frame.pack(fill="x")
        self._progress = ttk.Progressbar(prog_frame, mode="determinate", maximum=100)
        self._progress.pack(fill="x", pady=(0, 4))
        self._status_label = ttk.Label(prog_frame, text="대기 중")
        self._status_label.pack(anchor="w")

    def _do_search(self) -> None:
        query = self._search_entry.get().strip()
        if not query:
            return
        self._status_label.config(text="검색 중...")
        self.update()
        self._novels = self._on_search(query, self._search_type.get())
        self._listbox.delete(0, "end")
        for novel in self._novels:
            status = "구독중" if novel.is_subscribed else "미구독"
            self._listbox.insert("end", f"[{status}] {novel.title}  — {novel.author}")
        self._status_label.config(text=f"검색 결과: {len(self._novels)}건")
        self._dl_btn.config(state="disabled")

    def _on_select(self, _event) -> None:
        idx = self._listbox.curselection()
        if idx and self._novels[idx[0]].is_subscribed:
            self._dl_btn.config(state="normal")
        else:
            self._dl_btn.config(state="disabled")

    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self._folder_var.set(folder)

    def _start_download(self) -> None:
        idx = self._listbox.curselection()
        if not idx:
            return
        novel = self._novels[idx[0]]
        base_dir = Path(self._folder_var.get())
        base_dir.mkdir(parents=True, exist_ok=True)
        self._dl_btn.config(state="disabled")
        self._progress["value"] = 0

        def progress_cb(current: int, total: int, title: str) -> None:
            self._progress["value"] = (current / total * 100) if total else 0
            self._status_label.config(text=f"{current}/{total}화 — {title}")
            self.update_idletasks()

        def run() -> None:
            self._on_download(novel.novel_id, novel.title, base_dir, progress_cb)
            self.after(0, lambda: self._status_label.config(text="완료!"))
            self.after(0, lambda: self._dl_btn.config(state="normal"))

        Thread(target=run, daemon=True).start()
