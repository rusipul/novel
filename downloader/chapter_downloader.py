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
        """GoFullPage 방식: CSS !important 주입으로 내부 스크롤 제한 해제 후
        full_page 스크린샷 한 장으로 전체 캡처, 뷰포트 단위로 잘라 PDF 저장."""
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

            # !important CSS 주입 — 높이 고정·overflow 제한 모두 해제
            page.add_style_tag(content="""
                #novel_text, #novel_box, #viewer_no_drag,
                [id^="novel_"], [class*="viewer_wrap"], [class*="novel_view"],
                [class*="viewer-wrap"], [class*="novel-view"] {
                    overflow: visible !important;
                    height: auto !important;
                    max-height: none !important;
                    min-height: 0 !important;
                }
                body, html {
                    overflow-y: visible !important;
                    height: auto !important;
                }
            """)

            # 레이아웃 재계산 완료까지 높이가 안정될 때까지 대기 (최대 3초)
            prev_h = 0
            stable = 0
            for _ in range(30):
                cur_h = page.evaluate(
                    "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
                )
                if cur_h == prev_h:
                    stable += 1
                    if stable >= 4:  # 400ms 연속 안정
                        break
                else:
                    stable = 0
                    prev_h = cur_h
                time.sleep(0.1)
            time.sleep(0.2)

            # 전체 페이지 스크린샷 (body 높이 = 콘텐츠 전체)
            raw = page.screenshot(full_page=True)
            full_img = PILImage.open(io.BytesIO(raw)).convert("RGB")
            w, h = full_img.size

            # CSS 주입 후에도 1뷰포트 높이면 → 스크롤 방식 폴백
            if h <= vp_h + 50:
                raw = self._scroll_capture(page, vp_h)
                if raw:
                    full_img = PILImage.open(io.BytesIO(raw)).convert("RGB")
                    w, h = full_img.size

            if h == 0:
                return 0

            images = []
            y = 0
            while y < h:
                crop_h = min(vp_h, h - y)
                images.append(full_img.crop((0, y, w, y + crop_h)))
                y += vp_h

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

    def _scroll_capture(self, page, vp_h: int):
        """CSS 주입이 실패했을 때 스크롤하며 스크린샷을 찍고 세로로 이어붙인다."""
        try:
            from PIL import Image as PILImage
            import io as _io

            # 스크롤 가능한 컨테이너 탐색 (overflow auto/scroll인 요소)
            info = page.evaluate("""
                () => {
                    const ids = ['viewer_no_drag', 'novel_text', 'novel_box'];
                    for (const id of ids) {
                        const el = document.getElementById(id);
                        if (!el) continue;
                        const st = window.getComputedStyle(el);
                        const ov = st.overflow + ' ' + st.overflowY;
                        if ((ov.includes('auto') || ov.includes('scroll')) && el.scrollHeight > el.clientHeight + 50) {
                            return { id, sh: el.scrollHeight };
                        }
                    }
                    const winH = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
                    return { id: '__window__', sh: winH };
                }
            """)
            inner_id = info.get('id', '__window__')
            total_h = max(int(info.get('sh', vp_h)), vp_h)

            frames = []
            scroll_y = 0
            MAX_PAGES = 300

            while scroll_y < total_h and len(frames) < MAX_PAGES:
                if inner_id == '__window__':
                    page.evaluate(f"window.scrollTo(0, {scroll_y})")
                else:
                    page.evaluate(
                        f"(function(){{var e=document.getElementById('{inner_id}');if(e)e.scrollTop={scroll_y};}})()"
                    )
                time.sleep(0.3)
                frames.append(PILImage.open(_io.BytesIO(page.screenshot(full_page=False))).convert("RGB"))
                scroll_y += vp_h

            # 마지막 부분 누락 방지: 실제 맨 아래로 스크롤 후 추가 캡처
            if frames:
                if inner_id == '__window__':
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                else:
                    page.evaluate(
                        f"(function(){{var e=document.getElementById('{inner_id}');if(e)e.scrollTop=e.scrollHeight;}})()"
                    )
                time.sleep(0.3)
                last_frame = PILImage.open(_io.BytesIO(page.screenshot(full_page=False))).convert("RGB")
                # 이전 마지막 프레임과 다를 때만 추가 (내용이 더 있는 경우)
                if last_frame.tobytes() != frames[-1].tobytes():
                    frames.append(last_frame)

            if not frames:
                return None

            total_h_px = sum(f.size[1] for f in frames)
            combined = PILImage.new("RGB", (frames[0].size[0], total_h_px))
            y_off = 0
            for f in frames:
                combined.paste(f, (0, y_off))
                y_off += f.size[1]

            buf = _io.BytesIO()
            combined.save(buf, "PNG")
            return buf.getvalue()

        except Exception:
            return None
