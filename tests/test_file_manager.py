import pytest
from pathlib import Path
from storage.file_manager import (
    create_chapter_folder, save_text, save_image, log_error, chapter_exists
)

def test_create_chapter_folder(tmp_path):
    folder = create_chapter_folder(tmp_path, "소설명", 1, "첫번째화")
    assert folder == tmp_path / "소설명" / "001_첫번째화"
    assert folder.exists()

def test_chapter_num_zero_padded(tmp_path):
    folder = create_chapter_folder(tmp_path, "소설명", 42, "화제목")
    assert folder.name == "042_화제목"

def test_save_text(tmp_path):
    folder = create_chapter_folder(tmp_path, "소설", 1, "화")
    save_text(folder, "내용입니다")
    assert (folder / "text.txt").read_text(encoding="utf-8") == "내용입니다"

def test_save_image(tmp_path):
    folder = create_chapter_folder(tmp_path, "소설", 1, "화")
    save_image(folder, 1, b"\x89PNG")
    assert (folder / "page_001.png").read_bytes() == b"\x89PNG"

def test_save_image_page_num_padded(tmp_path):
    folder = create_chapter_folder(tmp_path, "소설", 1, "화")
    save_image(folder, 12, b"\x89PNG")
    assert (folder / "page_012.png").exists()

def test_log_error_creates_file(tmp_path):
    log_error(tmp_path, "소설명", 3, "네트워크 오류")
    log = (tmp_path / "소설명" / "errors.log").read_text(encoding="utf-8")
    assert "003" in log
    assert "네트워크 오류" in log

def test_log_error_appends(tmp_path):
    log_error(tmp_path, "소설명", 1, "첫번째 오류")
    log_error(tmp_path, "소설명", 2, "두번째 오류")
    log = (tmp_path / "소설명" / "errors.log").read_text(encoding="utf-8")
    assert "001" in log
    assert "002" in log

def test_chapter_exists_true(tmp_path):
    create_chapter_folder(tmp_path, "소설", 5, "화")
    assert chapter_exists(tmp_path, "소설", 5) is True

def test_chapter_exists_false(tmp_path):
    assert chapter_exists(tmp_path, "소설", 5) is False

def test_sanitize_invalid_chars(tmp_path):
    folder = create_chapter_folder(tmp_path, "소설/이름", 1, "화:제목")
    assert folder.exists()
