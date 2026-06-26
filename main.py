import queue
import threading
from pathlib import Path

from browser.novelpia_client import NovelPiaClient
from browser.session import BrowserSession
from downloader.chapter_downloader import ChapterDownloader
from downloader.scheduler import Scheduler
from gui.login_window import LoginWindow
from gui.main_window import MainWindow

# 세션 쿠키 저장 경로 (홈 디렉터리)
SESSION_FILE = str(Path.home() / ".novelpia_session.json")


def main() -> None:
    # Playwright의 sync API는 생성된 스레드에서만 사용 가능.
    # 전용 playwright 스레드가 모든 브라우저 작업을 처리한다.
    _task_q: queue.SimpleQueue = queue.SimpleQueue()
    _started = threading.Event()
    _refs: dict = {}

    def _playwright_worker() -> None:
        session = BrowserSession(headless=False)
        # 저장된 세션이 있으면 쿠키를 불러와 자동 로그인 시도
        session.start(storage_state=SESSION_FILE if Path(SESSION_FILE).exists() else None)
        _refs["client"] = NovelPiaClient(session)
        _refs["downloader"] = ChapterDownloader(session)
        _started.set()

        while True:
            fn = _task_q.get()
            if fn is None:
                break
            try:
                fn()
            except Exception as exc:
                print(f"[playwright] {exc}")

        session.stop()

    def _submit_sync(fn):
        """playwright 전용 스레드에서 fn을 실행하고 결과를 반환. 예외는 그대로 전파."""
        done = threading.Event()
        box: list = [None, None]  # [result, exception]

        def wrapper():
            try:
                box[0] = fn()
            except Exception as exc:
                box[1] = exc
            finally:
                done.set()

        _task_q.put(wrapper)
        done.wait()
        if box[1]:
            raise box[1]
        return box[0]

    threading.Thread(target=_playwright_worker, daemon=True).start()
    _started.wait()

    client = _refs["client"]
    downloader = _refs["downloader"]

    def on_search(query: str, search_type: str):
        return _submit_sync(lambda: client.search(query, search_type))

    def on_download(novel_id: str, novel_name: str, base_dir: Path, progress_cb) -> None:
        _submit_sync(
            lambda: Scheduler(client, downloader, base_dir).download_novel(
                novel_id, novel_name, progress_cb
            )
        )

    # 저장된 세션으로 자동 로그인 시도
    if Path(SESSION_FILE).exists():
        try:
            auto_ok = _submit_sync(client.try_auto_login)
        except Exception:
            auto_ok = False
        if auto_ok:
            MainWindow(on_search=on_search, on_download=on_download).mainloop()
            _task_q.put(None)
            return

    # 자동 로그인 실패 → 로그인 창 표시
    login_refs: dict = {}
    _login_ok = [False]

    def handle_start_login() -> None:
        try:
            _submit_sync(client.start_naver_login)
            login_refs["win"].after(0, login_refs["win"].show_confirm_button)
        except Exception as exc:
            login_refs["win"].after(
                0,
                lambda msg=str(exc): login_refs["win"].show_error(f"브라우저 열기 실패: {msg}"),
            )

    def handle_confirm_login() -> None:
        try:
            logged_in = _submit_sync(client.is_logged_in)
        except Exception:
            logged_in = False

        if logged_in:
            # 세션 쿠키 저장 → 다음 실행 시 자동 로그인
            try:
                _submit_sync(lambda: client.save_session(SESSION_FILE))
            except Exception:
                pass
            _login_ok[0] = True
            login_refs["win"].after(0, login_refs["win"].quit)
        else:
            login_refs["win"].after(
                0,
                lambda: login_refs["win"].show_error(
                    "아직 로그인이 완료되지 않았습니다.\n"
                    "자동으로 열린 Chromium 창에서 로그인을 완료한 뒤 다시 눌러주세요."
                ),
            )

    login_win = LoginWindow(
        on_naver_login=handle_start_login,
        on_login_confirm=handle_confirm_login,
    )
    login_refs["win"] = login_win
    login_win.mainloop()

    if _login_ok[0]:
        login_win.destroy()
        MainWindow(on_search=on_search, on_download=on_download).mainloop()

    _task_q.put(None)  # playwright 스레드 종료 신호


if __name__ == "__main__":
    main()
