from pathlib import Path

from browser.novelpia_client import NovelPiaClient
from browser.session import BrowserSession
from downloader.chapter_downloader import ChapterDownloader
from downloader.scheduler import Scheduler
from gui.login_window import LoginWindow
from gui.main_window import MainWindow


def main() -> None:
    # headless=False: 네이버 소셜 로그인은 브라우저 창이 보여야 함
    session = BrowserSession(headless=False)
    session.start()

    client = NovelPiaClient(session)
    downloader = ChapterDownloader(session)

    refs: dict = {}

    def handle_naver_login() -> None:
        success = client.login_naver()
        if success:
            refs["login"].after(0, refs["login"].destroy)
            refs["login"].after(0, _open_main)
        else:
            refs["login"].after(
                0,
                lambda: refs["login"].show_error(
                    "로그인 실패. 네이버 버튼을 찾지 못했거나 시간이 초과되었습니다."
                ),
            )

    def _open_main() -> None:
        def on_download(novel_id: str, novel_name: str, base_dir: Path, progress_cb) -> None:
            Scheduler(client, downloader, base_dir).download_novel(novel_id, novel_name, progress_cb)

        MainWindow(on_search=client.search, on_download=on_download).mainloop()

    login_win = LoginWindow(on_naver_login=handle_naver_login)
    refs["login"] = login_win
    login_win.mainloop()

    session.stop()


if __name__ == "__main__":
    main()
