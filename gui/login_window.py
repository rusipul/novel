import tkinter as tk
from threading import Thread
from tkinter import ttk
from typing import Callable


class LoginWindow(tk.Tk):
    def __init__(self, on_naver_login: Callable[[], None]):
        super().__init__()
        self._on_naver_login = on_naver_login
        self.title("노벨피아 다운로더 - 로그인")
        self.geometry("320x180")
        self.resizable(False, False)
        self._build()

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=24)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="노벨피아 다운로더", font=("", 13, "bold")).pack(pady=(0, 16))

        self._naver_btn = ttk.Button(
            frame,
            text="네이버로 로그인",
            command=self._on_click,
            width=24,
        )
        self._naver_btn.pack(pady=(0, 8))

        self._status_label = ttk.Label(frame, text="", foreground="#555", wraplength=270)
        self._status_label.pack()

    def _on_click(self) -> None:
        self._naver_btn.config(state="disabled")
        self._status_label.config(
            text="브라우저 창에서 네이버 로그인을 완료해 주세요.\n완료 후 자동으로 진행됩니다."
        )
        self.update()
        Thread(target=self._on_naver_login, daemon=True).start()

    def show_error(self, message: str) -> None:
        self._status_label.config(text=message, foreground="red")
        self._naver_btn.config(state="normal")
