import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from browser.novelpia_client import NovelPiaClient, ChapterInfo
from downloader.chapter_downloader import ChapterDownloader, SessionExpiredError
from storage.file_manager import chapter_exists, create_chapter_folder, log_error


@dataclass
class SchedulerResult:
    total: int
    downloaded: int
    skipped: int
    failed: list[int] = field(default_factory=list)


ProgressCallback = Callable[[int, int, str], None]


class Scheduler:
    def __init__(
        self,
        client: NovelPiaClient,
        downloader: ChapterDownloader,
        base_dir: Path,
        delay_seconds: float = 1.5,
        max_retries: int = 3,
    ):
        self._client = client
        self._downloader = downloader
        self._base_dir = base_dir
        self._delay = delay_seconds
        self._max_retries = max_retries

    def download_novel(
        self,
        novel_id: str,
        novel_name: str,
        progress_cb: ProgressCallback | None = None,
    ) -> SchedulerResult:
        chapters = self._client.get_chapter_list(novel_id)
        result = SchedulerResult(total=len(chapters), downloaded=0, skipped=0)

        for chapter in chapters:
            if chapter_exists(self._base_dir, novel_name, chapter.chapter_num):
                result.skipped += 1
                continue

            if progress_cb:
                progress_cb(chapter.chapter_num, result.total, chapter.title)

            if self._download_with_retry(chapter, novel_name):
                result.downloaded += 1
            else:
                result.failed.append(chapter.chapter_num)

            time.sleep(self._delay)

        return result

    def _download_with_retry(self, chapter: ChapterInfo, novel_name: str) -> bool:
        for attempt in range(self._max_retries):
            try:
                chapter_dir = create_chapter_folder(
                    self._base_dir, novel_name, chapter.chapter_num, chapter.title
                )
                dl_result = self._downloader.download_chapter(chapter.url, chapter_dir)
                if dl_result.success:
                    return True
                log_error(self._base_dir, novel_name, chapter.chapter_num, dl_result.error)
            except SessionExpiredError:
                if self._client.relogin():
                    continue
                log_error(self._base_dir, novel_name, chapter.chapter_num, "세션 만료 후 재로그인 실패")
                return False
            except Exception as exc:
                if attempt == self._max_retries - 1:
                    log_error(self._base_dir, novel_name, chapter.chapter_num, str(exc))
                else:
                    time.sleep(2)
        return False
