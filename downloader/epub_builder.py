"""EPUB 생성 유틸리티.

build_chapter_epub : 단일 화 EPUB (chapter_dir 안에 저장)
build_full_epub    : 소설 전체 EPUB (novel_dir/전체본.epub)
"""
from __future__ import annotations

import json
from pathlib import Path

try:
    from ebooklib import epub
    _HAS_EPUB = True
except ImportError:
    _HAS_EPUB = False


_CSS = (
    "body{font-family:serif;line-height:1.9;margin:1.5em 2em;word-break:keep-all}"
    "h2{font-size:1.2em;margin:0 0 1.2em;border-bottom:1px solid #aaa;padding-bottom:.4em}"
    "p{margin:.4em 0;text-indent:1em}"
    ".img-wrap{text-align:center;margin:1em 0}"
    ".img-wrap img{max-width:100%;height:auto}"
)

_CSS_FILE = "style/default.css"


def _make_css_item() -> "epub.EpubItem":
    item = epub.EpubItem(
        uid="style_default",
        file_name=_CSS_FILE,
        media_type="text/css",
        content=_CSS.encode("utf-8"),
    )
    return item


def _xhtml(title: str, body_html: str) -> str:
    return (
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="ko">'
        f'<head><meta charset="UTF-8"/><title>{title}</title></head>'
        f'<body>{body_html}</body></html>'
    )


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── 단일 화 EPUB ─────────────────────────────────────────────────────────────

def build_chapter_epub(chapter_dir: Path) -> Path | None:
    """chapter_dir 안의 manifest.json + 이미지를 읽어 단일 화 EPUB을 생성한다."""
    if not _HAS_EPUB:
        return None

    manifest_path = chapter_dir / "manifest.json"
    if not manifest_path.exists():
        return None

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chapter_num: int = manifest["chapter_num"]
    chapter_title: str = manifest["chapter_title"]
    items: list[dict] = manifest["items"]

    book = epub.EpubBook()
    header_text = f"&lt;&lt;{chapter_num}화&gt;&gt; {_escape(chapter_title)}"
    book.set_title(f"{chapter_num:03d}화 {chapter_title}")
    book.set_language("ko")

    css_item = _make_css_item()
    book.add_item(css_item)

    html_parts: list[str] = [f"<h2>{header_text}</h2>"]
    epub_images: list[epub.EpubImage] = []

    for item in items:
        if item["type"] == "text":
            html_parts.append(f'<p>{_escape(item["content"])}</p>')
        elif item["type"] == "image":
            img_path = chapter_dir / item["file"]
            if not img_path.exists():
                continue
            ext = img_path.suffix.lstrip(".") or "jpg"
            media = f"image/{'jpeg' if ext == 'jpg' else ext}"
            img_epub_name = f"images/{item['file']}"
            img_item = epub.EpubImage()
            img_item.file_name = img_epub_name
            img_item.media_type = media
            img_item.content = img_path.read_bytes()
            epub_images.append(img_item)
            html_parts.append(
                f'<div class="img-wrap">'
                f'<img src="{img_epub_name}" alt="image"/>'
                f"</div>"
            )

    ch = epub.EpubHtml(
        title=f"{chapter_num}화 {chapter_title}",
        file_name=f"ch{chapter_num:03d}.xhtml",
        lang="ko",
    )
    ch.content = _xhtml(f"{chapter_num}화", "\n".join(html_parts))
    ch.add_link(href=_CSS_FILE, rel="stylesheet", type="text/css")

    book.add_item(ch)
    for img in epub_images:
        book.add_item(img)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.toc = [epub.Link(f"ch{chapter_num:03d}.xhtml", f"{chapter_num}화 {chapter_title}", f"ch{chapter_num:03d}")]
    book.spine = [ch]

    stem = chapter_dir.name
    out = chapter_dir / f"{stem}.epub"
    epub.write_epub(str(out), book)
    return out


# ── 전체본 EPUB ───────────────────────────────────────────────────────────────

def build_full_epub(novel_dir: Path, novel_name: str) -> Path | None:
    """novel_dir 하위 각 화 폴더의 manifest.json을 읽어 전체본 EPUB을 생성한다."""
    if not _HAS_EPUB:
        return None

    book = epub.EpubBook()
    book.set_title(novel_name)
    book.set_language("ko")
    book.add_item(_make_css_item())

    epub_chapters: list[epub.EpubHtml] = []
    toc_items: list[epub.Link] = []
    img_global: int = 0

    ch_dirs = sorted(
        [d for d in novel_dir.iterdir() if d.is_dir()],
        key=lambda d: int(d.name.split("_")[0]) if d.name.split("_")[0].isdigit() else 9999,
    )

    for ch_dir in ch_dirs:
        manifest_path = ch_dir / "manifest.json"
        # manifest가 없으면 txt만 사용 (구버전 호환)
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            chapter_num: int = manifest["chapter_num"]
            chapter_title: str = manifest["chapter_title"]
            items: list[dict] = manifest["items"]
        else:
            parts = ch_dir.name.split("_", 1)
            try:
                chapter_num = int(parts[0])
            except ValueError:
                continue
            chapter_title = parts[1] if len(parts) > 1 else f"{chapter_num}화"
            txt = ch_dir / f"{ch_dir.name}.txt"
            if not txt.exists():
                txt = ch_dir / "text.txt"
            if not txt.exists():
                continue
            raw = txt.read_text(encoding="utf-8")
            # <<N화>> 헤더 줄 제거 (중복 방지)
            lines_raw = raw.split("\n")
            if lines_raw and lines_raw[0].startswith("<<") and lines_raw[0].endswith(">>"):
                lines_raw = lines_raw[2:]  # 헤더 + 빈줄 제거
            items = [{"type": "text", "content": l} for l in lines_raw if l.strip()]

        header_text = f"&lt;&lt;{chapter_num}화&gt;&gt; {_escape(chapter_title)}"
        html_parts: list[str] = [f"<h2>{header_text}</h2>"]

        for item in items:
            if item["type"] == "text":
                content = item.get("content", "")
                if content:
                    html_parts.append(f'<p>{_escape(content)}</p>')
            elif item["type"] == "image":
                img_path = ch_dir / item["file"]
                if not img_path.exists():
                    continue
                ext = img_path.suffix.lstrip(".") or "jpg"
                media = f"image/{'jpeg' if ext == 'jpg' else ext}"
                global_name = f"img_{img_global:05d}.{ext}"
                img_global += 1
                img_item = epub.EpubImage()
                img_item.file_name = f"images/{global_name}"
                img_item.media_type = media
                img_item.content = img_path.read_bytes()
                book.add_item(img_item)
                html_parts.append(
                    f'<div class="img-wrap">'
                    f'<img src="images/{global_name}" alt="image"/>'
                    f"</div>"
                )

        ch = epub.EpubHtml(
            title=f"{chapter_num}화 {chapter_title}",
            file_name=f"ch{chapter_num:03d}.xhtml",
            lang="ko",
        )
        ch.content = _xhtml(f"{chapter_num}화 {chapter_title}", "\n".join(html_parts))
        ch.add_link(href=_CSS_FILE, rel="stylesheet", type="text/css")
        book.add_item(ch)
        epub_chapters.append(ch)
        toc_items.append(
            epub.Link(f"ch{chapter_num:03d}.xhtml", f"{chapter_num}화 {chapter_title}", f"ch{chapter_num:03d}")
        )

    if not epub_chapters:
        return None

    book.toc = toc_items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = epub_chapters

    out = novel_dir / "전체본.epub"
    epub.write_epub(str(out), book)
    return out
