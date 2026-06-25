import tkinter as tk
from tkinter import ttk
from typing import Callable


class LoginWindow(tk.Tk):
    def __init__(self, on_success: Callable[[str, str], None]):
        super().__init__()
        self._on_success = on_success
        self.title("노벨피아 다운로더 - 로그인")
        self.geometry("320x210")
        self.resizable(False, False)
        self._build()

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="아이디").grid(row=0, column=0, sticky="w", pady=4)
        self._username = ttk.Entry(frame, width=25)
        self._username.grid(row=0, column=1, pady=4, padx=(8, 0))

        ttk.Label(frame, text="비밀번호").grid(row=1, column=0, sticky="w", pady=4)
        self._password = ttk.Entry(frame, width=25, show="*")
        self._password.grid(row=1, column=1, pady=4, padx=(8, 0))

        self._error_label = ttk.Label(frame, text="", foreground="red", wraplength=260)
        self._error_label.grid(row=2, column=0, columnspan=2, pady=4)

        ttk.Button(frame, text="로그인", command=self._on_login_click).grid(
            row=3, column=0, columnspan=2, pady=8
        )

        self._username.focus()
        self.bind("<Return>", lambda _: self._on_login_click())

    def _on_login_click(self) -> None:
        username = self._username.get().strip()
        password = self._password.get().strip()
        if not username or not password:
            self.show_error("아이디와 비밀번호를 입력하세요.")
            return
        self.show_error("로그인 중...")
        self.update()
        self._on_success(username, password)

    def show_error(self, message: str) -> None:
        self._error_label.config(text=message)
