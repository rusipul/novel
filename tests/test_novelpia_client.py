from unittest.mock import MagicMock
from browser.novelpia_client import NovelPiaClient, NovelInfo, ChapterInfo


def _make_client(page_mock):
    session = MagicMock()
    session.page = page_mock
    return NovelPiaClient(session)


def test_login_success_when_redirected():
    page = MagicMock()
    page.url = "https://novelpia.com/"
    client = _make_client(page)
    assert client.login("user@test.com", "pw123") is True
    page.goto.assert_called_once_with("https://novelpia.com/login")


def test_login_failure_when_still_on_login_page():
    page = MagicMock()
    page.url = "https://novelpia.com/login"
    page.query_selector.return_value = MagicMock()
    client = _make_client(page)
    assert client.login("user@test.com", "wrong") is False


def test_search_returns_subscribed_novel():
    page = MagicMock()
    item = MagicMock()
    title_el = MagicMock()
    title_el.inner_text.return_value = "소설 제목  "
    author_el = MagicMock()
    author_el.inner_text.return_value = "작가명"
    badge_el = MagicMock()
    link_el = MagicMock()
    link_el.get_attribute.return_value = "/novel/99"

    def qs(sel):
        return {
            NovelPiaClient.SEL_NOVEL_TITLE: title_el,
            NovelPiaClient.SEL_NOVEL_AUTHOR: author_el,
            NovelPiaClient.SEL_SUBSCRIPTION_BADGE: badge_el,
            "a[href*='/novel/']": link_el,
        }.get(sel)

    item.query_selector.side_effect = qs
    page.query_selector_all.return_value = [item]
    client = _make_client(page)
    results = client.search("소설", "title")
    assert results == [NovelInfo(novel_id="99", title="소설 제목", author="작가명", is_subscribed=True)]


def test_search_unsubscribed_novel():
    page = MagicMock()
    item = MagicMock()
    title_el = MagicMock()
    title_el.inner_text.return_value = "미구독소설"
    author_el = MagicMock()
    author_el.inner_text.return_value = "작가"
    link_el = MagicMock()
    link_el.get_attribute.return_value = "/novel/77"

    def qs(sel):
        return {
            NovelPiaClient.SEL_NOVEL_TITLE: title_el,
            NovelPiaClient.SEL_NOVEL_AUTHOR: author_el,
            NovelPiaClient.SEL_SUBSCRIPTION_BADGE: None,
            "a[href*='/novel/']": link_el,
        }.get(sel)

    item.query_selector.side_effect = qs
    page.query_selector_all.return_value = [item]
    client = _make_client(page)
    results = client.search("미구독", "title")
    assert results[0].is_subscribed is False


def test_get_chapter_list():
    page = MagicMock()
    row = MagicMock()
    title_el = MagicMock()
    title_el.inner_text.return_value = "1화 제목"
    link_el = MagicMock()
    link_el.get_attribute.return_value = "/viewer/555"

    def qs(sel):
        return {
            NovelPiaClient.SEL_CHAPTER_TITLE: title_el,
            "a[href*='/viewer/']": link_el,
        }.get(sel)

    row.query_selector.side_effect = qs
    page.query_selector_all.return_value = [row]
    client = _make_client(page)
    chapters = client.get_chapter_list("99")
    assert chapters == [ChapterInfo(chapter_num=1, title="1화 제목", url="https://novelpia.com/viewer/555")]


def test_relogin_uses_stored_credentials():
    page = MagicMock()
    page.url = "https://novelpia.com/"
    client = _make_client(page)
    client.login("user@test.com", "pw")
    page.reset_mock()
    page.url = "https://novelpia.com/"
    assert client.relogin() is True
    page.goto.assert_called_with("https://novelpia.com/login")
