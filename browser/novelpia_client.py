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
    SEL_NAVER_BTN = "a[href*='naver'], .btn-naver, [class*='naver-login'], img[alt*='네이버']"
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

    def start_naver_login(self) -> None:
        """로그인 페이지로 이동하고 네이버 버튼 클릭을 시도한다."""
        page = self._session.page
        page.goto(f"{BASE_URL}/login")
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass
        try:
            page.click(self.SEL_NAVER_BTN, timeout=5_000)
        except Exception:
            pass  # 버튼을 못 찾아도 사용자가 브라우저에서 직접 클릭 가능

    def is_logged_in(self) -> bool:
        """로그인 여부를 확인한다.
        노벨피아는 SPA — 네이버 OAuth 완료 후에도 URL이 /login에 머무름.
        로그인 폼(비밀번호 입력창)이 사라졌으면 로그인 성공으로 판단."""
        try:
            page = self._session.page
            url = page.url
            if "novelpia.com" not in url:
                return False
            if "/login" not in url:
                return True
            # SPA: URL이 /login이어도 폼이 없으면 로그인 완료
            login_form = page.query_selector("input[type='password'], .login-form, #login-form")
            return login_form is None
        except Exception:
            return False

    def login_naver(self, timeout_ms: int = 300_000) -> bool:
        """자동 폴링 방식 로그인 (하위 호환 유지)."""
        import time as _time
        self.start_naver_login()
        deadline = _time.time() + timeout_ms / 1000
        while _time.time() < deadline:
            if self.is_logged_in():
                return True
            _time.sleep(1)
        return False

    def search(self, query: str, search_type: str = "title") -> list[NovelInfo]:
        from urllib.parse import quote
        encoded = quote(query)
        url = (
            f"{BASE_URL}/search/all//1/{encoded}"
            "?page=1&rows=30&novel_type=&sort_col=last_viewdate"
            "&block_out=0&block_stop=0&is_contest=0&is_challenge=0&list_display=list"
        )
        page = self._session.page

        # 전략 1: goto(commit) — URL이 커밋되면 즉시 반환, 로드 완료를 기다리지 않음
        try:
            page.goto(url, wait_until="commit", timeout=15_000)
        except Exception:
            # 전략 2: JS 네비게이션 — "context was destroyed"는 네비게이션 중 정상 발생
            try:
                page.evaluate("u => { window.location.href = u; }", url)
            except Exception:
                pass

        # 어떤 방법으로든 네비게이션이 시작됐으면 로드 완료 대기
        try:
            page.wait_for_load_state("domcontentloaded", timeout=20_000)
        except Exception:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=8_000)
        except Exception:
            pass

        # CSS 선택자 대신 JS로 /novel/{id} 링크를 직접 추출 — 실제 HTML 구조에 독립적
        try:
            raw: list[dict] = page.evaluate("""
                () => {
                    const seen = new Set();
                    const results = [];
                    document.querySelectorAll('a[href]').forEach(a => {
                        const m = a.href.match(/\\/novel\\/(\\d+)/);
                        if (!m || seen.has(m[1])) return;
                        seen.add(m[1]);
                        // 줄바꿈→공백, 3칸 이상→2칸(구분자 보존), trim 후 첫 2칸 앞까지만 제목
                        const raw = a.textContent.replace(/[\\n\\r\\t]/g, ' ').replace(/ {3,}/g, '  ');
                        const trimmed = raw.trim();
                        const spIdx = trimmed.search(/ {2,}/);
                        const title = (spIdx > 0 ? trimmed.slice(0, spIdx) : trimmed).slice(0, 80);
                        let author = '';
                        const card = a.closest('li, tr, article, .item') || a.parentElement;
                        if (card) {
                            card.querySelectorAll('[class*="author"], [class*="writer"], [class*="nick"]')
                                .forEach(el => {
                                    const t = el.textContent.trim();
                                    if (t && t.length < 30) author = t;
                                });
                        }
                        if (title) results.push({ id: m[1], title, author });
                    });
                    return results;
                }
            """) or []
        except Exception:
            raw = []

        return [
            NovelInfo(
                novel_id=item["id"],
                title=item["title"],
                author=item.get("author", ""),
                is_subscribed=True,  # TODO: HTML 구조 파악 후 실제 구독 배지로 대체
            )
            for item in raw
            if item.get("title")
        ]

    def get_chapter_list(self, novel_id: str) -> list[ChapterInfo]:
        page = self._session.page
        url = f"{BASE_URL}/novel/{novel_id}"

        try:
            page.goto(url, wait_until="commit", timeout=15_000)
        except Exception:
            try:
                page.evaluate("u => { window.location.href = u; }", url)
            except Exception:
                pass

        try:
            page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=8_000)
        except Exception:
            pass

        # JS로 /viewer/ 링크를 직접 추출 — CSS 선택자보다 HTML 구조에 독립적
        try:
            raw: list[dict] = page.evaluate("""
                () => {
                    const seen = new Set();
                    const results = [];
                    document.querySelectorAll('a[href]').forEach(a => {
                        if (!a.href.includes('/viewer/')) return;
                        if (seen.has(a.href)) return;
                        seen.add(a.href);

                        // 부모 카드에서 제목 요소 탐색
                        let title = '';
                        const card = a.closest('li, tr, .item, .episode-item') || a.parentElement;
                        if (card) {
                            const titleEl = card.querySelector(
                                '[class*="title"], [class*="ep_title"], [class*="episode_title"],'
                                + '[class*="ep-title"], [class*="subject"], .s_inv_bold'
                            );
                            if (titleEl) title = titleEl.textContent.trim().slice(0, 60);
                        }

                        // 제목 없으면 링크 텍스트에서 N화 패턴 추출
                        if (!title) {
                            const raw = a.textContent.replace(/[\\n\\r\\t]/g, ' ').trim();
                            const m = raw.match(/\\d+\\s*화/);
                            title = m ? m[0].replace(/\\s+/g, '') : raw.slice(0, 60);
                        }

                        results.push({ url: a.href, title });
                    });
                    return results;
                }
            """) or []
        except Exception:
            raw = []

        import re as _re

        def _ep_num(item: dict) -> int:
            m = _re.search(r"(\d+)화", item.get("title", ""))
            return int(m.group(1)) if m else 9999

        raw.sort(key=_ep_num)

        return [
            ChapterInfo(
                chapter_num=_ep_num(item) if _ep_num(item) != 9999 else i + 1,
                title=item.get("title", f"{i + 1}화") or f"{i + 1}화",
                url=item["url"],
            )
            for i, item in enumerate(raw)
        ]

    def try_auto_login(self) -> bool:
        """저장된 세션 쿠키로 자동 로그인을 시도한다.
        노벨피아 홈으로 이동해 로그인 상태를 확인한다."""
        page = self._session.page
        try:
            page.goto(f"{BASE_URL}", wait_until="domcontentloaded", timeout=15_000)
            try:
                page.wait_for_load_state("networkidle", timeout=5_000)
            except Exception:
                pass
            # 로그인 상태: 유저 메뉴/마이페이지 링크 존재 여부로 판단
            user_el = page.query_selector(
                "a[href*='/mypage'], a[href*='/my/'], "
                "[class*='user_name'], [class*='username'], "
                "[class*='my_info'], [class*='myinfo'], .s_nav_my"
            )
            if user_el:
                return True
            # 로그인 버튼이 있으면 세션 만료
            login_el = page.query_selector(
                "a[href='/login'], a[href*='login'], .btn_login, [class*='btn-login']"
            )
            return login_el is None
        except Exception:
            return False

    def save_session(self, path: str) -> None:
        """현재 로그인 세션(쿠키)을 파일로 저장한다."""
        self._session.save_state(path)

    def relogin(self) -> bool:
        if self._credentials:
            return self.login(*self._credentials)
        return False  # 소셜 로그인은 자동 재로그인 불가
