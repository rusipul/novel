from pathlib import Path
from unittest.mock import MagicMock
from browser.novelpia_client import ChapterInfo
from downloader.chapter_downloader import DownloadResult, SessionExpiredError
from downloader.scheduler import Scheduler, SchedulerResult


def _chapter(num: int, title: str = "화제목") -> ChapterInfo:
    return ChapterInfo(chapter_num=num, title=title, url=f"https://novelpia.com/viewer/{num}")


def _make_scheduler(tmp_path, client, downloader, delay=0, max_retries=3):
    return Scheduler(client, downloader, tmp_path, delay_seconds=delay, max_retries=max_retries)


def test_downloads_all_chapters(tmp_path):
    client = MagicMock()
    downloader = MagicMock()
    client.get_chapter_list.return_value = [_chapter(1), _chapter(2)]
    downloader.download_chapter.return_value = DownloadResult(success=True, page_count=1)
    result = _make_scheduler(tmp_path, client, downloader).download_novel("n1", "소설")
    assert result.downloaded == 2
    assert result.failed == []


def test_skips_existing_chapter(tmp_path):
    client = MagicMock()
    downloader = MagicMock()
    client.get_chapter_list.return_value = [_chapter(1), _chapter(2)]
    (tmp_path / "소설" / "001_화제목").mkdir(parents=True)
    downloader.download_chapter.return_value = DownloadResult(success=True, page_count=1)
    result = _make_scheduler(tmp_path, client, downloader).download_novel("n1", "소설")
    assert result.skipped == 1
    assert result.downloaded == 1
    assert downloader.download_chapter.call_count == 1


def test_retries_failed_chapter_three_times(tmp_path):
    client = MagicMock()
    downloader = MagicMock()
    client.get_chapter_list.return_value = [_chapter(1)]
    downloader.download_chapter.return_value = DownloadResult(success=False, page_count=0, error="오류")
    result = _make_scheduler(tmp_path, client, downloader).download_novel("n1", "소설")
    assert downloader.download_chapter.call_count == 3
    assert result.failed == [1]


def test_failed_chapter_logged(tmp_path):
    client = MagicMock()
    downloader = MagicMock()
    client.get_chapter_list.return_value = [_chapter(3, "세번째화")]
    downloader.download_chapter.return_value = DownloadResult(success=False, page_count=0, error="실패메시지")
    Scheduler(client, downloader, tmp_path, delay_seconds=0, max_retries=1).download_novel("n1", "소설")
    log = (tmp_path / "소설" / "errors.log").read_text(encoding="utf-8")
    assert "003" in log
    assert "실패메시지" in log


def test_progress_callback_receives_each_chapter(tmp_path):
    client = MagicMock()
    downloader = MagicMock()
    client.get_chapter_list.return_value = [_chapter(1), _chapter(2)]
    downloader.download_chapter.return_value = DownloadResult(success=True, page_count=1)
    calls = []
    _make_scheduler(tmp_path, client, downloader).download_novel(
        "n1", "소설", progress_cb=lambda cur, total, title: calls.append(cur)
    )
    assert calls == [1, 2]


def test_exception_caught_and_chapter_logged_as_failed(tmp_path):
    client = MagicMock()
    downloader = MagicMock()
    client.get_chapter_list.return_value = [_chapter(1)]
    downloader.download_chapter.side_effect = Exception("crash")
    result = Scheduler(client, downloader, tmp_path, delay_seconds=0, max_retries=1).download_novel("n1", "소설")
    assert result.failed == [1]


def test_session_expired_triggers_relogin(tmp_path):
    client = MagicMock()
    downloader = MagicMock()
    client.get_chapter_list.return_value = [_chapter(1)]
    client.relogin.return_value = True
    downloader.download_chapter.side_effect = [
        SessionExpiredError("expired"),
        DownloadResult(success=True, page_count=1),
    ]
    result = _make_scheduler(tmp_path, client, downloader).download_novel("n1", "소설")
    client.relogin.assert_called_once()
    assert result.downloaded == 1
