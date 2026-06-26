from datetime import datetime
from pathlib import Path


def create_chapter_folder(base_dir: Path, novel_name: str, chapter_num: int, chapter_title: str) -> Path:
    folder = Path(base_dir) / _sanitize(novel_name) / f"{chapter_num:03d}_{_sanitize(chapter_title)}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def save_text(chapter_dir: Path, text: str) -> None:
    (chapter_dir / "text.txt").write_text(text, encoding="utf-8")


def save_image(chapter_dir: Path, page_num: int, image_bytes: bytes) -> None:
    (chapter_dir / f"page_{page_num:03d}.png").write_bytes(image_bytes)


def log_error(base_dir: Path, novel_name: str, chapter_num: int, message: str) -> None:
    log_path = Path(base_dir) / _sanitize(novel_name) / "errors.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] Chapter {chapter_num:03d}: {message}\n")


def chapter_exists(base_dir: Path, novel_name: str, chapter_num: int) -> bool:
    novel_dir = Path(base_dir) / _sanitize(novel_name)
    if not novel_dir.exists():
        return False
    prefix = f"{chapter_num:03d}_"
    try:
        return any(d.name.startswith(prefix) for d in novel_dir.iterdir() if d.is_dir())
    except FileNotFoundError:
        return False


def _sanitize(name: str) -> str:
    name = name.replace("\n", " ").replace("\r", "").replace("\t", " ")
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    while "  " in name:
        name = name.replace("  ", " ")
    name = name.strip()[:80].strip()
    return name if name else "unnamed"
