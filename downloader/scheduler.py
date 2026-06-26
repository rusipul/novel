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

        # 모든 화 완료 후 통합 텍스트 파일 생성
        self._merge_text(novel_name, chapters)

        return result

    def _merge_text(self, novel_name: str, chapters: list) -> None:
        """각 화의 text.txt를 화 번호 순으로 합쳐 전체본.txt를 생성한다."""
        from storage.file_manager import _sanitize
        novel_dir = self._base_dir / _sanitize(novel_name)
        if not novel_dir.exists():
            return

        parts: list[tuple[int, str]] = []
        for ch_dir in novel_dir.iterdir():
            if not ch_dir.is_dir():
                continue
            txt = ch_dir / "text.txt"
            if not txt.exists():
                continue
            # 폴더명 앞 숫자(화 번호)로 정렬
            try:
                num = int(ch_dir.name.split("_")[0])
            except ValueError:
                num = 9999
            parts.append((num, txt.read_text(encoding="utf-8")))

        if not parts:
            return

        parts.sort(key=lambda x: x[0])

        merged_lines = []
        for num, text in parts:
            # 해당 화 번호의 제목 찾기
            ch_title = next(
                (c.title for c in chapters if c.chapter_num == num),
                f"{num}화"
            )
            merged_lines.append(f"{'='*40}")
            merged_lines.append(f"【{ch_title}】")
            merged_lines.append(f"{'='*40}")
            merged_lines.append(text)
            merged_lines.append("")

        (novel_dir / "전체본.txt").write_text(
            "\n".join(merged_lines), encoding="utf-8"
        )

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
