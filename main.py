import queue
import sys
import threading
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from browser.novelpia_client import NovelPiaClient
from browser.session import BrowserSession
from downloader.chapter_downloader import ChapterDownloader
from downloader.scheduler import Scheduler
from gui.login_window import LoginWindow
from gui.main_window import MainWindow


def main() -> None:
    # Playwright의 sync API는 생성된 스레드에서만 사용 가능.
    # 전용 playwright 스레드가 모든 브라우저 작업을 처리한다.
    _task_q: queue.SimpleQueue = queue.SimpleQueue()
    _started = threading.Event()
    _refs: dict = {}

    def _playwright_worker() -> None:
        session = BrowserSession(headless=False)
        session.start()
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
    login_refs: dict = {}
    _login_ok = [False]

    def handle_start_login() -> None:
        # "① 네이버로 로그인" 버튼 클릭 시 — 브라우저를 열고 네이버 버튼을 클릭한다.
        try:
            _submit_sync(client.start_naver_login)
            login_refs["win"].after(0, login_refs["win"].show_confirm_button)
        except Exception as exc:
            login_refs["win"].after(
                0,
                lambda msg=str(exc): login_refs["win"].show_error(f"브라우저 열기 실패: {msg}"),
            )

    def handle_confirm_login() -> None:
        # "② 로그인 완료" 버튼 클릭 시
        # OAuth 후 브라우저가 Naver 등 외부 페이지에 있을 수 있으므로
        # 노벨피아 홈으로 이동해 쿠키 기반으로 로그인 상태를 재확인한다.
        def _check():
            import time as _t
            page = client._session.page
            # 노벨피아 도메인이 아니면 홈으로 이동
            if "novelpia.com" not in page.url:
                try:
                    page.goto("https://novelpia.com", wait_until="domcontentloaded", timeout=15_000)
                    _t.sleep(1)
                except Exception:
                    pass
            return client.is_logged_in()

        try:
            logged_in = _submit_sync(_check)
        except Exception:
            logged_in = False

        if logged_in:
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

    def on_search(query: str, search_type: str):
        return _submit_sync(lambda: client.search(query, search_type))

    def on_download(novel_id: str, novel_name: str, base_dir: Path, progress_cb) -> None:
        _submit_sync(
            lambda: Scheduler(client, downloader, base_dir, delay_seconds=5.0).download_novel(
                novel_id, novel_name, progress_cb
            )
        )

    login_win = LoginWindow(
        on_naver_login=handle_start_login,
        on_login_confirm=handle_confirm_login,
    )
    login_refs["win"] = login_win
    login_win.mainloop()  # 로그인 성공 시 quit()으로 여기서 반환됨

    if _login_ok[0]:
        login_win.destroy()
        MainWindow(on_search=on_search, on_download=on_download).mainloop()

    _task_q.put(None)  # playwright 스레드 종료 신호


if __name__ == "__main__":
    main()
