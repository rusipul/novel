from pathlib import Path

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page


class BrowserSession:
    def __init__(self, headless: bool = True):
        self._headless = headless
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def start(self, storage_state: str | None = None) -> None:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self._headless)
        ctx_kwargs: dict = {
            "viewport": {"width": 1280, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        if storage_state and Path(storage_state).exists():
            ctx_kwargs["storage_state"] = storage_state
        self._context = self._browser.new_context(**ctx_kwargs)
        self._page = self._context.new_page()
        # JS alert/confirm/prompt를 브라우저 레벨에서 무음 처리.
        # page.on("dialog", ...) 핸들러 안에서 sync API를 호출하면 greenlet 충돌이 발생하므로
        # init_script로 window.alert 자체를 덮어써서 dialog 이벤트가 아예 발생하지 않게 한다.
        self._page.add_init_script(
            "window.alert = () => {};"
            "window.confirm = () => true;"
            "window.prompt = () => '';"
        )

    def save_state(self, path: str) -> None:
        """현재 쿠키/localStorage를 파일로 저장한다."""
        if self._context:
            self._context.storage_state(path=path)

    def stop(self) -> None:
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("BrowserSession not started. Call start() first.")
        return self._page
