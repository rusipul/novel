import tkinter as tk
from threading import Thread
from tkinter import ttk
from typing import Callable


class LoginWindow(tk.Tk):
    def __init__(
        self,
        on_naver_login: Callable[[], None],
        on_login_confirm: Callable[[], None],
    ):
        super().__init__()
        self._on_naver_login = on_naver_login
        self._on_login_confirm = on_login_confirm
        self.title("노벨피아 다운로더 - 로그인")
        self.geometry("320x230")
        self.resizable(False, False)
        self._build()

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=24)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="노벨피아 다운로더", font=("", 13, "bold")).pack(pady=(0, 16))

        self._naver_btn = ttk.Button(
            frame,
            text="① 네이버로 로그인 (브라우저 열기)",
            command=self._on_naver_click,
            width=30,
        )
        self._naver_btn.pack(pady=(0, 6))

        self._confirm_btn = ttk.Button(
            frame,
            text="② 로그인 완료",
            command=self._on_confirm_click,
            width=30,
            state="disabled",
        )
        self._confirm_btn.pack(pady=(0, 10))

        self._status_label = ttk.Label(frame, text="", foreground="#555", wraplength=270)
        self._status_label.pack()

    def _on_naver_click(self) -> None:
        self._naver_btn.config(state="disabled")
        self._status_label.config(
            text="⚠ 자동으로 열린 Chromium 창에서 네이버로 로그인해 주세요.\n"
                 "(기존 Edge/Chrome 브라우저가 아닌 새로 열린 창)\n"
                 "로그인 완료 후 아래 [② 로그인 완료] 버튼을 눌러주세요.",
            foreground="#333",
        )
        self.update()
        Thread(target=self._on_naver_login, daemon=True).start()

    def _on_confirm_click(self) -> None:
        self._confirm_btn.config(state="disabled")
        self._status_label.config(text="확인 중...", foreground="#555")
        self.update()
        Thread(target=self._on_login_confirm, daemon=True).start()

    def show_confirm_button(self) -> None:
        """브라우저가 열린 후 완료 버튼을 활성화한다."""
        self._confirm_btn.config(state="normal")

    def show_error(self, message: str) -> None:
        self._status_label.config(text=message, foreground="red")
        self._confirm_btn.config(state="normal")
