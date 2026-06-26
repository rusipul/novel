import io
import time
from dataclasses import dataclass
from pathlib import Path

from browser.session import BrowserSession


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

        try:
            page.goto(chapter_url, wait_until="commit", timeout=15_000)
        except Exception:
            try:
                page.evaluate("u => { window.location.href = u; }", chapter_url)
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

        if "/login" in page.url:
            raise SessionExpiredError("Session expired — redirected to login page")

        # 구독 모달 / 팝업 제거
        self._dismiss_modals(page)

        text = self._extract_text(page)
        if not text:
            return DownloadResult(success=False, page_count=0, error="콘텐츠 영역을 찾지 못했습니다")

        (chapter_dir / "text.txt").write_text(text, encoding="utf-8")

        page_count = self._save_pdf(page, chapter_dir / "chapter.pdf")
        return DownloadResult(success=True, page_count=page_count)

    def _dismiss_modals(self, page) -> None:
        """구독 안내 등 팝업/모달을 닫는다."""
        try:
            page.keyboard.press("Escape")
            time.sleep(0.3)
        except Exception:
            pass
        try:
            page.evaluate("""
                () => {
                    document.querySelectorAll(
                        '.modal, .popup, .layer-popup, .dim, .dimmed, .layer_wrap,'
                        + '[class*="modal"], [class*="popup"], [class*="overlay"],'
                        + '[class*="subscribe"], [class*="payment"]'
                    ).forEach(el => {
                        if (el.offsetParent !== null) el.remove();
                    });
                }
            """)
            time.sleep(0.2)
        except Exception:
            pass

    def _extract_text(self, page) -> str:
        """소설 본문 텍스트를 추출한다.
        노벨피아 뷰어는 #novel_text 안에 #line_1, #line_2, ... 형태로 각 줄을 렌더링."""
        try:
            return page.evaluate("""
                () => {
                    // 방법 1: #line_N 요소들을 번호순으로 수집
                    const lineEls = [...document.querySelectorAll('[id^="line_"]')]
                        .filter(el => /^line_\\d+$/.test(el.id))
                        .sort((a, b) => parseInt(a.id.slice(5)) - parseInt(b.id.slice(5)));
                    if (lineEls.length > 0) {
                        return lineEls.map(el => (el.textContent || '').trim()).join('\\n');
                    }
                    // 방법 2: #novel_text 전체
                    const nt = document.getElementById('novel_text');
                    if (nt) {
                        const t = (nt.textContent || '').trim();
                        if (t.length > 100) return t;
                    }
                    // 방법 3: #novel_box
                    const nb = document.getElementById('novel_box');
                    if (nb) {
                        const t = (nb.textContent || '').trim();
                        if (t.length > 100) return t;
                    }
                    return '';
                }
            """) or ""
        except Exception:
            return ""

    def _save_pdf(self, page, output_path: Path) -> int:
        """GoFullPage 방식으로 전체 챕터를 PDF로 저장한다.
        조상 요소의 height/overflow를 모두 해제해 창 스크롤로 전환한 뒤
        뷰포트 단위로 찍어 이어붙인다 — full_page=True 캔버스 높이 제한을 피함."""
        try:
            from PIL import Image as PILImage
        except ImportError:
            try:
                output_path.with_suffix(".png").write_bytes(page.screenshot(full_page=False))
            except Exception:
                pass
            return 1

        try:
            vp_h = int(page.evaluate("() => window.innerHeight") or 900)

            # 소설 컨테이너부터 body까지 모든 조상의 height/overflow 제한 해제
            # → 내부 스크롤이 창 스크롤로 전환됨
            page.evaluate("""
                () => {
                    const root = document.getElementById('novel_text')
                               || document.getElementById('novel_box')
                               || document.getElementById('viewer_no_drag');
                    if (root) {
                        let el = root;
                        while (el && el.tagName !== 'BODY') {
                            el.style.setProperty('overflow',   'visible', 'important');
                            el.style.setProperty('height',     'auto',    'important');
                            el.style.setProperty('max-height', 'none',    'important');
                            el.style.setProperty('min-height', '0',       'important');
                            el = el.parentElement;
                        }
                    }
                    document.body.style.setProperty('overflow-y', 'visible', 'important');
                    document.body.style.setProperty('height',     'auto',    'important');
                    document.documentElement.style.setProperty('overflow-y', 'visible', 'important');
                    document.documentElement.style.setProperty('height',     'auto',    'important');
                }
            """)

            # 레이아웃 안정화 대기 (최대 3초)
            prev_h = 0
            stable = 0
            for _ in range(30):
                cur_h = page.evaluate(
                    "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
                )
                if cur_h == prev_h:
                    stable += 1
                    if stable >= 4:
                        break
                else:
                    stable = 0
                    prev_h = cur_h
                time.sleep(0.1)
            time.sleep(0.2)

            total_h = int(page.evaluate(
                "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
            ))
            total_h = max(total_h, vp_h)

            # 맨 위에서 시작
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(0.2)

            images = []
            scroll_y = 0
            MAX_PAGES = 500

            while scroll_y < total_h and len(images) < MAX_PAGES:
                page.evaluate(f"window.scrollTo(0, {scroll_y})")
                time.sleep(0.25)
                images.append(PILImage.open(io.BytesIO(page.screenshot(full_page=False))).convert("RGB"))
                scroll_y += vp_h

            # 마지막 부분 누락 방지: 실제 맨 아래 스크롤 후 추가 캡처
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.25)
            last_img = PILImage.open(io.BytesIO(page.screenshot(full_page=False))).convert("RGB")
            # 이전 프레임과 실제로 다를 때만 추가 (스크롤 위치 비교)
            actual_bottom = page.evaluate("() => window.pageYOffset")
            if not images or int(actual_bottom) > scroll_y - vp_h:
                images.append(last_img)

            if not images:
                return 0

            images[0].save(
                str(output_path), "PDF", resolution=96.0,
                save_all=True, append_images=images[1:],
            )
            return len(images)

        except Exception:
            try:
                output_path.with_suffix(".png").write_bytes(page.screenshot(full_page=False))
            except Exception:
                pass
            return 1
