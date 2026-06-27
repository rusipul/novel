import base64
import io
import json
import time
from dataclasses import dataclass
from pathlib import Path

from browser.session import BrowserSession
from downloader.epub_builder import build_chapter_epub


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

        self._dismiss_modals(page)
        self._scroll_for_images(page)

        # chapter_dir.name 형식: "001_프롤로그"
        stem = chapter_dir.name
        parts = stem.split("_", 1)
        try:
            chapter_num = int(parts[0])
        except ValueError:
            chapter_num = 0
        chapter_title = parts[1] if len(parts) > 1 else stem

        # 텍스트 + 이미지 아이템 순서대로 추출
        raw_items = self._extract_content_items(page)
        if not raw_items:
            return DownloadResult(success=False, page_count=0, error="콘텐츠 영역을 찾지 못했습니다")

        # 이미지 다운로드, manifest 구성
        img_counter = 0
        manifest_items: list[dict] = []
        text_lines: list[str] = []

        for item in raw_items:
            if item["type"] == "text":
                content = item.get("content", "")
                if content:
                    manifest_items.append({"type": "text", "content": content})
                    text_lines.append(content)
            elif item["type"] == "image":
                src = item.get("src", "")
                if not src:
                    continue
                img_bytes = self._fetch_image_bytes(page, src)
                if img_bytes:
                    ext = src.rsplit(".", 1)[-1].lower().split("?")[0]
                    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
                        ext = "jpg"
                    if ext == "jpeg":
                        ext = "jpg"
                    img_filename = f"img_{img_counter:04d}.{ext}"
                    img_counter += 1
                    (chapter_dir / img_filename).write_bytes(img_bytes)
                    manifest_items.append({"type": "image", "file": img_filename})

        if not manifest_items:
            return DownloadResult(success=False, page_count=0, error="콘텐츠 영역을 찾지 못했습니다")

        # 한국어 문자 수 검증 — 쓰레기값(세션 만료·인코딩 오류) 감지
        korean_count = sum(
            1 for item in manifest_items if item["type"] == "text"
            for c in item.get("content", "") if "가" <= c <= "힣"
        )
        img_count = sum(1 for item in manifest_items if item["type"] == "image")
        if korean_count < 20 and img_count == 0:
            return DownloadResult(
                success=False, page_count=0,
                error=f"한국어 텍스트 부족 (한글 {korean_count}자) — 세션 만료 의심"
            )

        # <<N화>> 헤더 포함 텍스트 파일 저장
        header = f"<<{chapter_num}화>>"
        txt_content = header + "\n\n" + "\n".join(text_lines)
        (chapter_dir / f"{stem}.txt").write_text(txt_content, encoding="utf-8")

        # manifest.json 저장 (epub_builder 입력)
        manifest = {
            "chapter_num": chapter_num,
            "chapter_title": chapter_title,
            "items": manifest_items,
        }
        (chapter_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 단일 화 EPUB 생성
        try:
            build_chapter_epub(chapter_dir)
        except Exception:
            pass

        page_count = self._save_pdf(page, chapter_dir / f"{stem}.pdf")
        return DownloadResult(success=True, page_count=page_count)

    def _scroll_for_images(self, page) -> None:
        """소설 컨테이너 overflow 해제 + 전 페이지 스크롤로 lazy-load 이미지를 트리거한다."""
        try:
            page.evaluate("""
                async () => {
                    // overflow 해제로 내부 스크롤 → 창 스크롤 전환
                    const root = document.getElementById('novel_text')
                               || document.getElementById('novel_box')
                               || document.getElementById('viewer_no_drag');
                    if (root) {
                        let el = root;
                        while (el && el.tagName !== 'BODY') {
                            el.style.setProperty('overflow',   'visible', 'important');
                            el.style.setProperty('height',     'auto',    'important');
                            el.style.setProperty('max-height', 'none',    'important');
                            el = el.parentElement;
                        }
                    }
                    document.body.style.setProperty('overflow-y', 'visible', 'important');
                    document.documentElement.style.setProperty('overflow-y', 'visible', 'important');

                    // 전체 페이지를 뷰포트 절반씩 스크롤
                    const step = Math.max(window.innerHeight / 2, 300);
                    const total = document.body.scrollHeight;
                    for (let y = 0; y <= total + step; y += step) {
                        window.scrollTo(0, y);
                        await new Promise(r => setTimeout(r, 80));
                    }
                    window.scrollTo(0, 0);
                    await new Promise(r => setTimeout(r, 200));
                }
            """)
        except Exception:
            pass

    def _dismiss_modals(self, page) -> None:
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

    def _extract_content_items(self, page) -> list[dict]:
        """line_N 요소 + 소설 컨테이너 내 img를 DOM 순서대로 수집해 반환한다."""
        try:
            items = page.evaluate("""
                () => {
                    const IMG_ATTRS = [
                        'src','currentSrc','data-src','data-lazy-src',
                        'data-original','data-url','data-lazy','data-echo',
                    ];
                    // UI 이미지 경로 제외 (배너·아이콘·뱃지 등 소설 본문과 무관)
                    const UI_PATH = /\/img\/new\/|\/icon\/|\/banner|\/badge|\/btn_|\/common\//i;
                    const getImgSrc = img => {
                        for (const a of IMG_ATTRS) {
                            const v = (a === 'src' || a === 'currentSrc')
                                ? img[a] : img.getAttribute(a);
                            if (v && v.startsWith('http') && !v.includes('blank')
                                   && !v.includes('placeholder') && !v.includes('data:')
                                   && !UI_PATH.test(v)) {
                                return v;
                            }
                        }
                        return '';
                    };

                    const lineEls = [...document.querySelectorAll('[id^="line_"]')]
                        .filter(el => /^line_\\d+$/.test(el.id))
                        .sort((a, b) => parseInt(a.id.slice(5)) - parseInt(b.id.slice(5)));

                    // line_N이 없으면 novel_text/novel_box 전체를 단일 텍스트로 폴백
                    if (lineEls.length === 0) {
                        const c = document.getElementById('novel_text')
                               || document.getElementById('novel_box');
                        if (c) {
                            const t = c.textContent.trim();
                            if (t.length > 50) return [{type:'text', content:t}];
                        }
                        return [];
                    }

                    // line_N 요소의 공통 부모(소설 컨테이너)
                    const container = lineEls[0].closest(
                        '#novel_text, #novel_box, #viewer_no_drag, .novel_view, .viewer_content'
                    ) || lineEls[0].parentElement;

                    // 컨테이너 내 모든 line_N + img 를 DOM 순서로 정렬
                    const candidates = container
                        ? [...container.querySelectorAll('[id^="line_"], img')]
                        : lineEls;

                    const seenLine = new Set();
                    const seenSrc  = new Set();
                    const result = [];

                    for (const el of candidates) {
                        if (el.tagName === 'IMG') {
                            // line_N 안에 있는 img는 해당 line_N 처리 시 함께 수집
                            if (el.closest('[id^="line_"]')) continue;
                            const src = getImgSrc(el);
                            if (src && !seenSrc.has(src)) {
                                seenSrc.add(src);
                                result.push({type:'image', src});
                            }
                        } else if (/^line_\\d+$/.test(el.id)) {
                            if (seenLine.has(el.id)) continue;
                            seenLine.add(el.id);
                            const innerImgs = el.querySelectorAll('img');
                            if (innerImgs.length > 0) {
                                for (const img of innerImgs) {
                                    const src = getImgSrc(img);
                                    if (src && !seenSrc.has(src)) {
                                        seenSrc.add(src);
                                        result.push({type:'image', src});
                                    }
                                }
                                const clone = el.cloneNode(true);
                                clone.querySelectorAll('img').forEach(i => i.remove());
                                const text = clone.textContent.trim();
                                if (text) result.push({type:'text', content:text});
                            } else {
                                const text = (el.textContent || '').trim();
                                if (text) result.push({type:'text', content:text});
                            }
                        }
                    }
                    return result;
                }
            """) or []

            # 디버그: 이미지 발견 여부 출력
            imgs = [i for i in items if i.get("type") == "image"]
            if imgs:
                print(f"[IMG] {len(imgs)}개 이미지 발견")
                for img in imgs[:3]:
                    print(f"  {img['src'][:80]}")
            return items
        except Exception as e:
            print(f"[ERROR] _extract_content_items: {e}")
            return []

    def _fetch_image_bytes(self, page, url: str) -> bytes | None:
        """Playwright APIRequestContext로 이미지를 다운로드한다.
        브라우저 컨텍스트의 쿠키와 스토리지를 완전히 공유하므로 유료 회차 CDN도 통과한다."""
        try:
            response = page.context.request.get(
                url,
                headers={"Referer": "https://novelpia.com/"},
                timeout=15_000,
            )
            if response.ok:
                body = response.body()
                if len(body) > 500:
                    return body
                print(f"[IMG-DL] 응답 너무 작음 ({len(body)}B): {url[-60:]}")
            else:
                print(f"[IMG-DL] HTTP {response.status}: {url[-60:]}")
            return None
        except Exception as e:
            print(f"[IMG-DL] 오류: {e} — {url[-60:]}")
            # fallback: requests with cookies
            try:
                import requests as _requests
                cookies = {c["name"]: c["value"] for c in page.context.cookies()}
                ua = page.evaluate("() => navigator.userAgent") or ""
                resp = _requests.get(url, cookies=cookies, timeout=15,
                                     headers={"Referer": "https://novelpia.com/", "User-Agent": ua})
                if resp.ok and len(resp.content) > 500:
                    return resp.content
            except Exception:
                pass
            return None

    def _save_pdf(self, page, output_path: Path) -> int:
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

            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.25)
            last_img = PILImage.open(io.BytesIO(page.screenshot(full_page=False))).convert("RGB")
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
