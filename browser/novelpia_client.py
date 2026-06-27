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

        # 에피소드 목록 전체가 로드될 때까지 천천히 스크롤 (무한 스크롤 / 지연 로드 대응)
        try:
            for _ in range(8):
                prev_h: int = page.evaluate("document.body.scrollHeight")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                _time.sleep(0.6)
                new_h: int = page.evaluate("document.body.scrollHeight")
                if new_h == prev_h:
                    break
            page.evaluate("window.scrollTo(0, 0)")
            _time.sleep(0.3)
        except Exception:
            pass

        # 소설 목록 페이지에서 에피소드 ID→제목 매핑 미리 수집
        # 먼저 첫 번째 카드의 구조를 덤프해서 어떤 텍스트가 있는지 확인
        try:
            card_dump = page.evaluate("""
                () => {
                    const RE_VW = /viewer[\\/'"]+(\\d+)|check_next_episode_link\\((\\d+)\\)|go_viewer\\((\\d+)\\)/i;
                    const first = [...document.querySelectorAll('[onclick]')].find(el => {
                        const m = (el.getAttribute('onclick') || '').match(RE_VW);
                        return !!m;
                    });
                    if (!first) return null;
                    const card = first.closest('li,tr,article,[class*="episode"],[class*="ep_"]') || first;
                    return {
                        html: card.innerHTML.slice(0, 500),
                        text: card.textContent.trim().slice(0, 300),
                        childTexts: [...card.querySelectorAll('*')]
                            .filter(e => e.children.length === 0 && e.textContent.trim())
                            .map(e => ({ tag: e.tagName, cls: e.className.slice(0,30), text: e.textContent.trim().slice(0,60) }))
                            .slice(0, 15)
                    };
                }
            """)
            if card_dump:
                print(f"[DEBUG] 첫 에피소드 카드 텍스트: {card_dump['text']!r}")
                print(f"[DEBUG] 카드 리프 노드들:")
                for item in (card_dump.get('childTexts') or []):
                    print(f"  <{item['tag']} cls={item['cls']!r}> {item['text']!r}")
        except Exception as e:
            print(f"[DEBUG] 카드 덤프 실패: {e}")

        ep_title_map: dict[str, str] = {}
        try:
            raw_map: dict = page.evaluate("""
                () => {
                    const RE_VW = /viewer[\\/'"]+(\\d+)|check_next_episode_link\\((\\d+)\\)|go_viewer\\((\\d+)\\)/i;
                    const BAD_LINE = /^[\\d,]+$|^\\d+화$|이어보기|^(무료|유료|PLUS|성인|완결|미리보기|공지사항|\\d+코인)$/i;
                    const IS_DATE = /\\d{2,4}\\.\\d{1,2}\\.\\d{1,2}/;
                    const map = {};

                    const extractTitle = (card) => {
                        const tEl = card.querySelector('[class*="title"],[class*="tit"],[class*="subject"]');
                        if (tEl) {
                            const t = tEl.textContent.trim();
                            if (t && t.length > 1 && t.length < 100) return t.slice(0, 80);
                        }
                        const fullText = card.textContent.trim();
                        const afterEp = fullText.replace(/EP\\.?\\s*\\d+/i, '').trim();
                        const lines = afterEp.split('\\n')
                            .map(l => l.trim())
                            .filter(l => l.length > 1 && !BAD_LINE.test(l) && !IS_DATE.test(l));
                        return lines.length ? lines[0].slice(0, 80) : '';
                    };

                    // onclick 기반 에피소드 링크
                    document.querySelectorAll('[onclick]').forEach(el => {
                        const oc = el.getAttribute('onclick') || '';
                        const m = oc.match(RE_VW);
                        if (!m) return;
                        const vid = m[1] || m[2] || m[3];
                        if (!vid || map[vid]) return;
                        const card = el.closest('li,tr,article,[class*="episode"],[class*="ep_"]') || el;
                        const t = extractTitle(card);
                        if (t) map[vid] = t;
                    });

                    // href 기반 viewer 링크 (PLUS 회차 등 onclick 없는 경우 보완)
                    // 단, 댓글 섹션([class*="comment"],[class*="reply"])의 링크는 제외
                    const COMMENT_PATTERN = /댓글|회차\s*:|작성됨|^[가-힣\w]{1,10}\s+\d{2}\.\d{2}/;
                    document.querySelectorAll('a[href*="/viewer/"]').forEach(a => {
                        // 댓글 컨테이너 안에 있으면 스킵
                        if (a.closest('[class*="comment"],[class*="reply"],[id*="comment"],[id*="reply"]')) return;
                        const m = a.href.match(/\\/viewer\\/(\\d+)/);
                        if (!m) return;
                        const vid = m[1];
                        if (map[vid]) return;
                        const card = a.closest('li,tr,article,[class*="episode"],[class*="ep_"]') || a;
                        const cardText = card.textContent.trim();
                        // 댓글 형태 텍스트 제외
                        if (COMMENT_PATTERN.test(cardText)) return;
                        const t = extractTitle(card);
                        if (t && t.length < 50 && !IS_DATE.test(t) && !COMMENT_PATTERN.test(t)) map[vid] = t;
                    });

                    return map;
                }
            """) or {}
            ep_title_map = {str(k): str(v) for k, v in raw_map.items()}
            print(f"[DEBUG] 에피소드 제목 매핑: {len(ep_title_map)}개 수집")
            for i, (k, v) in enumerate(ep_title_map.items()):
                if i >= 5: break
                print(f"  {k}: {v!r}")
        except Exception as e:
            print(f"[DEBUG] 에피소드 제목 매핑 실패: {e}")

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

        # 전략 1: 카드 텍스트에 'EP.0' 패턴이 있는 viewer 링크 (href 기반)
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

        # 전략 2: 모든 EP.N 라벨 파싱 → 번호가 가장 작은 화 (href 기반)
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
            print(f"[DEBUG] Strategy2 (min EP, href): ep={result2.get('ep')} url={first_url}")

        # 전략 3: onclick 속성에서 viewer ID 파싱 → EP.0 우선, 없으면 번호 최솟값
        if not first_url:
            result3: dict = page.evaluate("""
                () => {
                    // viewer/ID, check_next_episode_link(ID), go_viewer(ID) 등 모두 처리
                    const RE_VIEWER = /viewer[\\/'"]+(\\d+)|check_next_episode_link\\((\\d+)\\)|go_viewer\\((\\d+)\\)/i;
                    const candidates = [];
                    document.querySelectorAll('[onclick]').forEach(el => {
                        const oc = el.getAttribute('onclick') || '';
                        const m = oc.match(RE_VIEWER);
                        if (!m) return;
                        const vid = m[1] || m[2] || m[3];
                        const card = el.closest('li,tr,article,[class*="episode"],[class*="ep_"]') || el;
                        const text = card.textContent;
                        const epM = text.match(/EP\\.?\\s*(\\d+)/i);
                        const ep = epM ? parseInt(epM[1]) : 9999;
                        candidates.push({ ep, url: 'https://novelpia.com/viewer/' + vid });
                    });
                    if (!candidates.length) return { href: null, ep: null };
                    candidates.sort((a, b) => a.ep - b.ep);
                    return { href: candidates[0].url, ep: candidates[0].ep };
                }
            """) or {}
            first_url = result3.get('href')
            print(f"[DEBUG] Strategy3 (onclick attr): ep={result3.get('ep')} url={first_url}")

        # 전략 4: '첫화' 텍스트 링크 (href 기반)
        if not first_url:
            first_url = page.evaluate("""
                () => {
                    const a = [...document.querySelectorAll('a')]
                        .find(el => el.textContent.replace(/\\s+/g,'').includes('첫화')
                               && el.href && el.href.includes('/viewer/'));
                    return a ? a.href : null;
                }
            """)
            print(f"[DEBUG] Strategy4 (첫화 text): {first_url}")

        # 전략 5: EP.0 → EP.1 순으로 클릭 시도 → 네비게이션 후 page.url 캡처
        if not first_url:
            novel_url = page.url
            for ep_pattern, label in [
                (r"EP\.?\s*0(?!\d)", "EP.0"),
                (r"EP\.?\s*1(?!\d)", "EP.1"),
            ]:
                try:
                    locator = page.locator(f"text=/{ep_pattern}/i").first
                    if locator.count() == 0:
                        print(f"[DEBUG] Strategy5 ({label}): not found, trying next")
                        continue
                    with page.expect_navigation(timeout=10_000):
                        locator.click()
                    page.wait_for_load_state("domcontentloaded", timeout=10_000)
                    captured = page.url
                    if "/viewer/" in captured:
                        first_url = captured
                        print(f"[DEBUG] Strategy5 ({label} click): {first_url}")
                        break
                    # 뷰어가 아닌 페이지로 이동했으면 복귀 후 다음 패턴 시도
                    page.goto(novel_url, wait_until="domcontentloaded", timeout=15_000)
                except Exception as e:
                    print(f"[DEBUG] Strategy5 ({label} click) failed: {e}")
                    try:
                        page.goto(novel_url, wait_until="domcontentloaded", timeout=15_000)
                    except Exception:
                        pass

        # 전략 6: 에피소드 항목 첫 번째 클릭 → page.url 캡처 (EP 번호 무관)
        if not first_url:
            try:
                novel_url = page.url
                ep_any = page.locator("text=/EP\\.?\\s*\\d+/i").first
                if ep_any.count() > 0:
                    with page.expect_navigation(timeout=10_000):
                        ep_any.click()
                    page.wait_for_load_state("domcontentloaded", timeout=10_000)
                    captured = page.url
                    if "/viewer/" in captured:
                        first_url = captured
                        print(f"[DEBUG] Strategy6 (first EP click): {first_url}")
                    else:
                        page.goto(novel_url, wait_until="domcontentloaded", timeout=15_000)
            except Exception as e:
                print(f"[DEBUG] Strategy6 (first EP click) failed: {e}")

        # 전략 7: viewer 링크 중 하나를 잡아 '이전화' 체인으로 거슬러 올라감
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

            # 첫 화에서만 텍스트 노드 덤프 (제목 위치 파악용)
            if num == 1:
                dump = page.evaluate("""
                    () => {
                        const bad = /코인|coin|결제|구독|PLUS|멤버십|휴대폰|신용카드|카카오|네이버페이|문화누리|열람권|뱃지|왼딸/i;
                        const result = [];
                        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                        let node;
                        while ((node = walker.nextNode()) && result.length < 40) {
                            const t = node.textContent.trim();
                            if (t.length > 1 && t.length < 100 && !bad.test(t)) {
                                const p = node.parentElement;
                                result.push({
                                    text: t.slice(0, 80),
                                    tag: p.tagName,
                                    id: p.id,
                                    cls: p.className.slice(0, 50)
                                });
                            }
                        }
                        return result;
                    }
                """) or []
                print("[DEBUG] 뷰어 텍스트 노드 덤프 (처음 40개, 결제 UI 제외):")
                for item in dump:
                    print(f"  <{item['tag']} id={item['id']!r} cls={item['cls']!r}> {item['text']!r}")

            # 뷰어 페이지에서 에피소드 제목 추출
            title: str = page.evaluate("""
                () => {
                    const BAD = /코인|coin|결제|구독|subscribe|노벨피아|웹소설|이어보기|다음화|다음편|이전화|이전편/i;
                    const ok = t => t && t.length > 1 && t.length < 120 && !BAD.test(t);

                    // 1) JS 전역 변수 (Novelpia가 JS에 저장하는 경우)
                    const jsVars = [
                        window.ep_title, window.epi_title, window.episode_title,
                        window.epTitle, window.current_ep_title, window.ep_tit,
                        window.epi_tit, window.viewer_title,
                    ];
                    for (const v of jsVars) {
                        if (v && typeof v === 'string' && ok(v)) return v.slice(0, 80);
                    }

                    // 2) ID 기반 탐색
                    const ID_SELS = [
                        'ep_title', 'epi_title', 'episode_title', 'novel_ep_title',
                        'viewer_title', 'view_title', 'content_title', 'ep_name', 'epi_name',
                    ];
                    for (const id of ID_SELS) {
                        const el = document.getElementById(id);
                        if (el) {
                            const t = el.textContent.trim();
                            if (ok(t)) return t.slice(0, 80);
                        }
                    }

                    // 3) 클래스 기반 셀렉터
                    const CLS_SELS = [
                        '.ep_title', '.episode_title', '.view_title', '.viewer_title',
                        '[class*="ep_title"]', '[class*="episode_title"]',
                        '[class*="view_title"]', '[class*="viewer_title"]',
                        '.content_title', '[class*="content_title"]',
                    ];
                    for (const sel of CLS_SELS) {
                        const el = document.querySelector(sel);
                        if (el) {
                            const t = el.textContent.trim();
                            if (ok(t)) return t.slice(0, 80);
                        }
                    }

                    // 4) 뷰어 본문(#novel_text 등) 바로 앞 형제 요소에서 제목 탐색
                    for (const id of ['novel_text', 'novel_box', 'viewer_no_drag', 'novel_content']) {
                        const content = document.getElementById(id);
                        if (!content) continue;
                        let sib = content.previousElementSibling;
                        for (let i = 0; sib && i < 5; i++, sib = sib.previousElementSibling) {
                            const t = sib.textContent.trim();
                            if (ok(t) && t.length < 100) return t.slice(0, 80);
                        }
                    }

                    return '';
                }
            """) or f"{num}화"

            # 소설 목록 페이지의 매핑이 있으면 우선 사용
            ep_id = current_url.rstrip('/').split('/')[-1]
            if ep_title_map.get(ep_id):
                title = ep_title_map[ep_id]

            chapters.append(ChapterInfo(chapter_num=num, title=title, url=current_url))

            # 다음화 URL: #next_epi_btn_bottom 로드 대기 후 onclick 직접 파싱
            try:
                page.wait_for_selector('#next_epi_btn_bottom', timeout=5_000)
            except Exception:
                pass

            next_url: str | None = page.evaluate("""
                () => {
                    // Novelpia 뷰어의 다음화 버튼은 항상 id="next_epi_btn_bottom"
                    const btn = document.getElementById('next_epi_btn_bottom');
                    if (btn) {
                        const oc = btn.getAttribute('onclick') || '';
                        const m = oc.match(/check_next_episode_link\\((\\d+)\\)/);
                        if (m) return 'https://novelpia.com/viewer/' + m[1];
                        // href 기반 폴백
                        if (btn.tagName === 'A' && btn.href && btn.href.includes('/viewer/')) {
                            return btn.href;
                        }
                    }
                    // 임의 [onclick*=check_next] 요소 탐색
                    const any = document.querySelector('[onclick*="check_next_episode_link"]');
                    if (any) {
                        const m = (any.getAttribute('onclick') || '').match(/check_next_episode_link\\((\\d+)\\)/);
                        if (m) return 'https://novelpia.com/viewer/' + m[1];
                    }
                    // href 기반 "다음화" 링크
                    const RE_NEXT = /다음화|다음편/;
                    const a = [...document.querySelectorAll('a[href*="/viewer/"]')]
                        .find(el => RE_NEXT.test(el.textContent.replace(/\\s+/g, '')));
                    if (a) return a.href;
                    return null;
                }
            """)
            print(f"[DEBUG] ch{num} next_url (onclick): {next_url}")

            # onclick으로 URL을 얻지 못한 경우 → JS 클릭 후 URL 폴링
            if not next_url:
                try:
                    is_last: bool = page.evaluate("""
                        () => /등록된\\s*마지막\\s*회차|마지막\\s*회차입니다/
                            .test(document.body.innerText)
                    """) or False

                    if is_last:
                        print(f"[DEBUG] ch{num}: 등록된 마지막 회차 감지 → 종료")
                    else:
                        prev_url = page.url

                        # JS .click() — 가시성 무관하게 이벤트 발생
                        page.evaluate("""
                            () => {
                                const btn = document.getElementById('next_epi_btn_bottom');
                                if (btn) { btn.click(); return; }
                                const RE = /다음화|다음편/;
                                const el = [...document.querySelectorAll('[onclick]')]
                                    .find(e => RE.test(e.textContent.trim()));
                                if (el) el.click();
                            }
                        """)

                        # URL 변화 폴링 (최대 12초)
                        captured = prev_url
                        for _ in range(24):
                            _time.sleep(0.5)
                            captured = page.url
                            if "/viewer/" in captured and captured != prev_url:
                                break

                        if "/viewer/" in captured and captured != current_url:
                            next_url = captured
                            print(f"[DEBUG] ch{num} next_url (js-click): {next_url}")
                        else:
                            # 열람권 모달 확인
                            try:
                                tk = page.locator(".btn-free-ticket-use").first
                                if tk.count() > 0:
                                    print(f"[DEBUG] ch{num}: 열람권 버튼 → JS 클릭")
                                    page.evaluate("() => { const b = document.querySelector('.btn-free-ticket-use'); if(b) b.click(); }")
                                    for _ in range(20):
                                        _time.sleep(0.5)
                                        captured = page.url
                                        if "/viewer/" in captured and captured != prev_url:
                                            break
                                    if "/viewer/" in captured and captured != current_url:
                                        next_url = captured
                                        print(f"[DEBUG] ch{num} next_url (ticket): {next_url}")
                            except Exception as et:
                                print(f"[DEBUG] ch{num} ticket error: {et}")

                            if not next_url:
                                print(f"[DEBUG] ch{num}: URL 변화 없음 → 마지막 회차")
                except Exception as e:
                    print(f"[DEBUG] ch{num} click failed: {e}")

            current_url = next_url
            num += 1
            _time.sleep(0.3)

        print(f"[DEBUG] get_chapter_list: {len(chapters)}화 수집 완료")
        return chapters

    def relogin(self) -> bool:
        if self._credentials:
            return self.login(*self._credentials)
        return False  # 소셜 로그인은 자동 재로그인 불가
