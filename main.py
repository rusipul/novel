from pathlib import Path

from browser.novelpia_client import NovelPiaClient
from browser.session import BrowserSession
from downloader.chapter_downloader import ChapterDownloader
from downloader.scheduler import Scheduler
from gui.login_window import LoginWindow
from gui.main_window import MainWindow


def main() -> None:
    session = BrowserSession(headless=True)
    session.start()

    client = NovelPiaClient(session)
    downloader = ChapterDownloader(session)

    refs: dict = {}

    def handle_login(username: str, password: str) -> None:
        if client.login(username, password):
            refs["login"].destroy()
            _open_main()
        else:
            refs["login"].show_error("로그인 실패. 아이디/비밀번호를 확인하세요.")

    def _open_main() -> None:
        def on_download(novel_id: str, novel_name: str, base_dir: Path, progress_cb) -> None:
            Scheduler(client, downloader, base_dir).download_novel(novel_id, novel_name, progress_cb)

        MainWindow(on_search=client.search, on_download=on_download).mainloop()

    login_win = LoginWindow(on_success=handle_login)
    refs["login"] = login_win
    login_win.mainloop()

    session.stop()


if __name__ == "__main__":
    main()
