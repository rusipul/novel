import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from browser.novelpia_client import NovelPiaClient, ChapterInfo
from downloader.chapter_downloader import ChapterDownloader, SessionExpiredError
from downloader.epub_builder import build_full_epub
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
        self._chapter_count = 0  # 실제 다운로드(건너뜀 포함) 누적 카운터

    def download_novel(
        self,
        novel_id: str,
        novel_name: str,
        progress_cb: ProgressCallback | None = None,
    ) -> SchedulerResult:
        chapters = self._client.get_chapter_list(novel_id)
        result = SchedulerResult(total=len(chapters), downloaded=0, skipped=0)
        print(f"[다운로드] 총 {len(chapters)}화 발견")

        for chapter in chapters:
            if chapter_exists(self._base_dir, novel_name, chapter.chapter_num):
                print(f"[건너뜀] {chapter.chapter_num}화: {chapter.title}")
                result.skipped += 1
                self._chapter_count += 1
                self._maybe_rest()
                continue

            print(f"[다운로드] {chapter.chapter_num}/{len(chapters)}화: {chapter.title}")
            if progress_cb:
                progress_cb(chapter.chapter_num, result.total, chapter.title)

            if self._download_with_retry(chapter, novel_name):
                print(f"[완료] {chapter.chapter_num}화: {chapter.title}")
                result.downloaded += 1
            else:
                print(f"[실패] {chapter.chapter_num}화: {chapter.title}")
                result.failed.append(chapter.chapter_num)

            self._chapter_count += 1
            self._maybe_rest()

            # 화 사이 딜레이: 기본값 + ±2초 랜덤 지터
            jitter = random.uniform(-2.0, 2.0)
            time.sleep(max(1.0, self._delay + jitter))

        self._merge_text(novel_name, chapters)
        self._build_full_epub(novel_name)

        return result

    def _merge_text(self, novel_name: str, chapters: list) -> None:
        """각 화의 .txt를 화 번호 순으로 합쳐 전체본.txt를 생성한다."""
        from storage.file_manager import _sanitize
        novel_dir = self._base_dir / _sanitize(novel_name)
        if not novel_dir.exists():
            return

        parts: list[tuple[int, str]] = []
        for ch_dir in novel_dir.iterdir():
            if not ch_dir.is_dir():
                continue
            txt = ch_dir / f"{ch_dir.name}.txt"
            if not txt.exists():
                txt = ch_dir / "text.txt"
            if not txt.exists():
                continue
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
            ch_title = next(
                (c.title for c in chapters if c.chapter_num == num),
                f"{num}화"
            )
            # <<N화>> 헤더가 있으면 제거 (전체본에서는 【제목】 구분선으로 대체)
            lines = text.split("\n")
            if lines and lines[0].startswith("<<") and lines[0].endswith(">>"):
                lines = lines[2:] if len(lines) > 1 and lines[1] == "" else lines[1:]
                text = "\n".join(lines)

            merged_lines.append(f"{'='*40}")
            merged_lines.append(f"【{ch_title}】")
            merged_lines.append(f"{'='*40}")
            merged_lines.append(text)
            merged_lines.append("")

        (novel_dir / "전체본.txt").write_text(
            "\n".join(merged_lines), encoding="utf-8"
        )

    def _build_full_epub(self, novel_name: str) -> None:
        """모든 화를 묶어 전체본.epub를 생성한다."""
        from storage.file_manager import _sanitize
        novel_dir = self._base_dir / _sanitize(novel_name)
        if not novel_dir.exists():
            return
        try:
            epub_path = build_full_epub(novel_dir, novel_name)
            if epub_path:
                print(f"[EPUB] 전체본 저장: {epub_path}")
        except Exception as e:
            print(f"[EPUB] 전체본 생성 실패: {e}")

    def _maybe_rest(self) -> None:
        """10화마다 keepalive, 30화마다 긴 휴식으로 속도제한을 방지한다."""
        if self._chapter_count % 30 == 0 and self._chapter_count > 0:
            rest = random.randint(45, 75)
            print(f"[REST] {self._chapter_count}화 도달 — {rest}초 휴식 (속도제한 방지)")
            time.sleep(rest)
            self._keepalive()
        elif self._chapter_count % 10 == 0 and self._chapter_count > 0:
            self._keepalive()

    def _keepalive(self) -> None:
        """Novelpia 메인을 방문해 세션 쿠키를 갱신한다."""
        try:
            page = self._downloader._session.page
            page.goto("https://novelpia.com/", wait_until="domcontentloaded", timeout=10_000)
            time.sleep(random.uniform(1.0, 2.5))
            print("[KEEPALIVE] 세션 유지 완료")
        except Exception as e:
            print(f"[KEEPALIVE] 실패: {e}")

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
