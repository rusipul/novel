from dataclasses import dataclass
from browser.session import BrowserSession

BASE_URL = "https://novelpia.com"


@dataclass
class NovelInfo:
    novel_id: str
    title: str
    author: str
    is_subscribed: bool


@dataclass
class ChapterInfo:
    chapter_num: int
    title: str
    url: str


class NovelPiaClient:
    # CSS selectors — update these if Novelpia changes their markup
    SEL_EMAIL = "input[name='email'], input[type='email']"
    SEL_PASSWORD = "input[name='password'], input[type='password']"
    SEL_LOGIN_BTN = "button[type='submit']"
    SEL_NOVEL_ITEM = ".novel-item, .book-item, [class*='novel-list'] li"
    SEL_NOVEL_TITLE = ".novel-title, .book-title, [class*='title']"
    SEL_NOVEL_AUTHOR = ".novel-author, .author, [class*='author']"
    SEL_SUBSCRIPTION_BADGE = ".subscribe-badge, .coin-badge, [class*='subscribe']"
    SEL_CHAPTER_ROW = ".ep-item, .chapter-item, [class*='episode'] li"
    SEL_CHAPTER_TITLE = ".ep-title, .chapter-title, [class*='title']"

    def __init__(self, session: BrowserSession):
        self._session = session
        self._credentials: tuple[str, str] | None = None

    def login(self, username: str, password: str) -> bool:
        self._credentials = (username, password)
        page = self._session.page
        page.goto(f"{BASE_URL}/login")
        page.wait_for_load_state("networkidle")
        page.fill(self.SEL_EMAIL, username)
        page.fill(self.SEL_PASSWORD, password)
        page.click(self.SEL_LOGIN_BTN)
        page.wait_for_load_state("networkidle")
        return "/login" not in page.url

    def search(self, query: str, search_type: str = "title") -> list[NovelInfo]:
        type_param = {"title": "novel", "author": "author", "tag": "tag"}.get(search_type, "novel")
        page = self._session.page
        page.goto(f"{BASE_URL}/novel?search={query}&searchType={type_param}")
        page.wait_for_load_state("networkidle")
        results = []
        for item in page.query_selector_all(self.SEL_NOVEL_ITEM):
            title_el = item.query_selector(self.SEL_NOVEL_TITLE)
            link_el = item.query_selector("a[href*='/novel/']")
            if not title_el or not link_el:
                continue
            author_el = item.query_selector(self.SEL_NOVEL_AUTHOR)
            badge_el = item.query_selector(self.SEL_SUBSCRIPTION_BADGE)
            href = link_el.get_attribute("href") or ""
            novel_id = href.split("/novel/")[-1].split("/")[0].split("?")[0]
            results.append(NovelInfo(
                novel_id=novel_id,
                title=title_el.inner_text().strip(),
                author=author_el.inner_text().strip() if author_el else "",
                is_subscribed=badge_el is not None,
            ))
        return results

    def get_chapter_list(self, novel_id: str) -> list[ChapterInfo]:
        page = self._session.page
        page.goto(f"{BASE_URL}/novel/{novel_id}")
        page.wait_for_load_state("networkidle")
        chapters = []
        for i, row in enumerate(page.query_selector_all(self.SEL_CHAPTER_ROW), start=1):
            title_el = row.query_selector(self.SEL_CHAPTER_TITLE)
            link_el = row.query_selector("a[href*='/viewer/']")
            if not title_el or not link_el:
                continue
            href = link_el.get_attribute("href") or ""
            url = href if href.startswith("http") else f"{BASE_URL}{href}"
            chapters.append(ChapterInfo(chapter_num=i, title=title_el.inner_text().strip(), url=url))
        return chapters

    def relogin(self) -> bool:
        if self._credentials:
            return self.login(*self._credentials)
        return False
