from unittest.mock import MagicMock, patch

from job_search_agent import tier2_crawler


def _fake_response(text, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


def test_extracts_from_jsonld_static_html():
    html = """
    <html><body>
    <script type="application/ld+json">
    {"@type": "JobPosting", "title": "Senior Program Manager",
     "datePosted": "2026-09-10T00:00:00Z",
     "hiringOrganization": {"name": "Acme"}, "url": "https://acme.example/jobs/1"}
    </script>
    </body></html>
    """
    client = MagicMock()
    client.get.return_value = _fake_response(html)

    postings = tier2_crawler.fetch("Acme", "https://acme.example/careers", client)

    assert len(postings) == 1
    assert postings[0].title == "Senior Program Manager"
    assert postings[0].date_confidence == "high"


def test_falls_back_to_render_when_static_page_is_empty():
    empty_html = "<html><body><div id='root'></div></body></html>"
    rendered_html = """
    <html><body>
    <a href="/careers/senior-program-manager">Senior Program Manager</a>
    <span>Posted 2 days ago</span>
    </body></html>
    """
    client = MagicMock()
    client.get.return_value = _fake_response(empty_html)

    renderer = MagicMock()
    renderer.available = True
    renderer.render.return_value = rendered_html

    postings = tier2_crawler.fetch("Acme", "https://acme.example/careers", client, renderer)

    renderer.render.assert_called_once_with("https://acme.example/careers")
    assert len(postings) == 1
    assert postings[0].title == "Senior Program Manager"
    assert postings[0].date_confidence == "low"


def test_sniffs_embedded_greenhouse_board_and_hands_off():
    html = '<html><body><iframe src="https://boards.greenhouse.io/embed/job_board?for=acme"></iframe></body></html>'
    client = MagicMock()
    client.get.return_value = _fake_response(html)

    with patch("job_search_agent.tier2_crawler.greenhouse.fetch") as mock_gh_fetch:
        mock_gh_fetch.return_value = ["fake-posting"]
        postings = tier2_crawler.fetch("Acme", "https://acme.example/careers", client)

    mock_gh_fetch.assert_called_once_with("Acme", "acme", client)
    assert postings == ["fake-posting"]


def test_zero_results_after_everything_returns_empty_list_not_error():
    html = "<html><body><div id='root'></div></body></html>"
    client = MagicMock()
    client.get.return_value = _fake_response(html)

    renderer = MagicMock()
    renderer.available = True
    renderer.render.return_value = None  # render attempted but failed

    postings = tier2_crawler.fetch("Acme", "https://acme.example/careers", client, renderer)
    assert postings == []


def test_http_failure_returns_empty_list():
    client = MagicMock()
    client.get.return_value = None
    assert tier2_crawler.fetch("Acme", "https://acme.example/careers", client) == []
