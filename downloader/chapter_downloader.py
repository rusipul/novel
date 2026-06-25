import time
from dataclasses import dataclass
from pathlib import Path

from browser.session import BrowserSession

# CSS selectors for the Novelpia viewer — update if markup changes
SEL_CONTENT = "#novel_view, .viewer-content, [class*='viewer'] [class*='content']"
SEL_PAGE_BTN = ".page-btn, [class*='page-num'], [class*='pagination'] button"


class SessionExpiredError(Exception):
    pass


@dataclass
class DownloadResult:
    success: bool
    page_count: int
    error: str = ""


class ChapterDownloader:
    def __init__(self, session: BrowserSession):
        self._session = session

    def download_chapter(self, chapter_url: str, chapter_dir: Path) -> DownloadResult:
        page = self._session.page
        page.goto(chapter_url)
        page.wait_for_load_state("networkidle")

        if "/login" in page.url:
            raise SessionExpiredError("Session expired — redirected to login page")

        text = self._extract_text(page)
        if not text:
            return DownloadResult(success=False, page_count=0, error="콘텐츠 영역을 찾지 못했습니다")

        (chapter_dir / "text.txt").write_text(text, encoding="utf-8")

        page_count = self._get_page_count(page)
        for page_num in range(1, page_count + 1):
            if page_num > 1:
                self._navigate_to_page(page, page_num)
            (chapter_dir / f"page_{page_num:03d}.png").write_bytes(page.screenshot(full_page=False))

        return DownloadResult(success=True, page_count=page_count)

    def _extract_text(self, page) -> str:
        el = page.query_selector(SEL_CONTENT)
        return el.inner_text().strip() if el else ""

    def _get_page_count(self, page) -> int:
        btns = page.query_selector_all(SEL_PAGE_BTN)
        return max(len(btns), 1)

    def _navigate_to_page(self, page, page_num: int) -> None:
        btns = page.query_selector_all(SEL_PAGE_BTN)
        if page_num - 1 < len(btns):
            btns[page_num - 1].click()
            page.wait_for_load_state("networkidle")
            time.sleep(0.5)
