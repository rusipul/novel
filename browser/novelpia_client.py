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
        """EP.0(첫 화)부터 '다음화 보기' 링크를 따라 전체 화 목록을 구성한다.
        화 제목에 숫자가 없어도 순서가 보장되고 페이지네이션 문제도 없다."""
        import time as _time
        page = self._session.page

        # 1. 소설 페이지에서 첫 화 URL 찾기
        try:
            page.goto(f"{BASE_URL}/novel/{novel_id}", wait_until="commit", timeout=15_000)
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

        # 에피소드 목록이 로드될 때까지 추가 대기 (댓글보다 늦게 로드되는 경우)
        try:
            page.wait_for_function(
                "() => /EP\\.?\\s*\\d+/i.test(document.body.innerText)",
                timeout=8_000,
            )
        except Exception:
            _time.sleep(2)

        # 에피소드 목록이 화면 밖에 있을 경우 스크롤로 로드 유도
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
            _time.sleep(0.5)
            page.evaluate("window.scrollTo(0, 0)")
            _time.sleep(0.3)
        except Exception:
            pass

        # 첫 화 URL 찾기: EP.0 라벨 기반 (공지사항과 구별하기 위해 EP 번호 직접 탐색)
        first_url: str | None = None

        # 디버그: EP.N 텍스트 여부와 링크 구조 파악
        debug_info: dict = page.evaluate("""
            () => {
                const bodyText = document.body.innerText;
                const hasEP0 = /EP\\.?\\s*0/i.test(bodyText);

                // EP.N 텍스트가 있는 카드에서 모든 링크 수집
                const allAnchors = [...document.querySelectorAll('a[href]')];
                const epAnchors = allAnchors.filter(a => {
                    const card = a.closest('li,tr,article,div,[class*="ep"]') || a.parentElement;
                    return card && /EP\\.?\\s*\\d+/i.test(card.textContent);
                });

                // viewer 링크 (기존)
                const viewerLinks = [...document.querySelectorAll('a[href*="/viewer/"]')];

                return {
                    hasEP0,
                    viewerCount: viewerLinks.length,
                    epAnchorCount: epAnchors.length,
                    epSamples: epAnchors.slice(0,5).map(a => ({
                        href: a.href.slice(-30),
                        text: a.textContent.trim().slice(0,50)
                    })),
                    viewerSamples: viewerLinks.slice(0,3).map(a => ({
                        href: a.href.slice(-20),
                        text: (a.closest('li,div') || a).textContent.replace(/\\s+/g,' ').trim().slice(0,60)
                    }))
                };
            }
        """) or {}
        print(f"[DEBUG] hasEP0={debug_info.get('hasEP0')}, viewerLinks={debug_info.get('viewerCount')}, epAnchors={debug_info.get('epAnchorCount')}")
        print(f"[DEBUG] EP anchors:")
        for item in debug_info.get('epSamples', []):
            print(f"  href=...{item['href']}  text={item['text']!r}")
        print(f"[DEBUG] viewer links:")
        for item in debug_info.get('viewerSamples', []):
            print(f"  href=...{item['href']}  text={item['text']!r}")

        # 전략 1: 카드 텍스트에 'EP.0' 패턴이 있는 viewer 링크
        first_url = page.evaluate("""
            () => {
                const links = [...document.querySelectorAll('a[href*="/viewer/"]')];
                for (const a of links) {
                    const card = a.closest('li,tr,article,[class*="episode"],[class*="ep_"]')
                                 || a.parentElement;
                    const text = card ? card.textContent : a.textContent;
                    if (/EP\\.?\\s*0(?!\\d)/i.test(text)) return a.href;
                }
                return null;
            }
        """)
        print(f"[DEBUG] Strategy1 (EP.0 card text): {first_url}")

        # 전략 2: 모든 EP.N 라벨 파싱 → 번호가 가장 작은 화
        if not first_url:
            result2: dict = page.evaluate("""
                () => {
                    const links = [...document.querySelectorAll('a[href*="/viewer/"]')];
                    let minEp = Infinity, minHref = null;
                    for (const a of links) {
                        const card = a.closest('li,tr,article,[class*="episode"],[class*="ep_"]')
                                     || a.parentElement;
                        const text = card ? card.textContent : a.textContent;
                        const m = text.match(/EP\\s*\\.?\\s*(\\d+)/i);
                        if (m) {
                            const ep = parseInt(m[1]);
                            if (ep < minEp) { minEp = ep; minHref = a.href; }
                        }
                    }
                    return { href: minHref, ep: minEp === Infinity ? null : minEp };
                }
            """) or {}
            first_url = result2.get('href')
            print(f"[DEBUG] Strategy2 (min EP): ep={result2.get('ep')} url={first_url}")

        # 전략 3: '첫화' 텍스트 링크
        if not first_url:
            first_url = page.evaluate("""
                () => {
                    const a = [...document.querySelectorAll('a')]
                        .find(el => el.textContent.replace(/\\s+/g,'').includes('첫화')
                               && el.href && el.href.includes('/viewer/'));
                    return a ? a.href : null;
                }
            """)

        # 전략 4: viewer 링크 중 하나를 잡아 '이전화' 체인으로 거슬러 올라감
        if not first_url:
            any_url: str | None = page.evaluate("""
                () => {
                    const links = [...document.querySelectorAll('a[href*="/viewer/"]')];
                    return links.length > 0 ? links[0].href : null;
                }
            """)
            if any_url:
                current = any_url
                for _ in range(1000):
                    try:
                        page.goto(current, wait_until="commit", timeout=10_000)
                        page.wait_for_load_state("domcontentloaded", timeout=8_000)
                    except Exception:
                        break
                    _time.sleep(0.2)
                    prev: str | None = page.evaluate("""
                        () => {
                            const a = [...document.querySelectorAll('a[href*="/viewer/"]')].find(el => {
                                const t = el.textContent.replace(/\\s+/g,'');
                                return t.includes('이전화') || t.includes('이전편');
                            });
                            return a ? a.href : null;
                        }
                    """)
                    if not prev:
                        first_url = current
                        break
                    current = prev

        if not first_url:
            return []

        # 2. 첫 화부터 '다음화 보기' 링크를 따라 전체 목록 수집
        chapters: list[ChapterInfo] = []
        current_url: str | None = first_url
        num = 1

        while current_url and num <= 2000:
            try:
                page.goto(current_url, wait_until="commit", timeout=15_000)
            except Exception:
                pass
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except Exception:
                pass

            # 팝업 제거 (구독 모달 등)
            try:
                page.keyboard.press("Escape")
                page.evaluate("""
                    () => document.querySelectorAll(
                        '.modal,[class*="modal"],[class*="popup"],[class*="overlay"]'
                    ).forEach(el => { if(el.offsetParent) el.remove(); })
                """)
            except Exception:
                pass

            # 뷰어 페이지에서 에피소드 제목 추출
            title: str = page.evaluate("""
                () => {
                    const sel = [
                        '.ep_title','.episode_title','[class*="ep_title"]',
                        '[class*="episode_title"]','.s_inv_bold','h2','h1'
                    ].join(',');
                    const el = document.querySelector(sel);
                    return el ? el.textContent.trim().slice(0,60) : '';
                }
            """) or f"{num}화"

            chapters.append(ChapterInfo(chapter_num=num, title=title, url=current_url))

            # 다음화 URL 추출 (클릭 없이 href만 가져옴)
            next_url: str | None = page.evaluate("""
                () => {
                    const a = [...document.querySelectorAll('a[href*="/viewer/"]')].find(el => {
                        const t = el.textContent.replace(/\\s+/g,'');
                        return t.includes('다음화') || t.includes('다음편');
                    });
                    return a ? a.href : null;
                }
            """)

            current_url = next_url
            num += 1
            _time.sleep(0.3)

        return chapters

    def relogin(self) -> bool:
        if self._credentials:
            return self.login(*self._credentials)
        return False  # 소셜 로그인은 자동 재로그인 불가
