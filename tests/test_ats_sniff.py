from job_search_agent.ats_sniff import sniff


def test_sniffs_greenhouse_iframe():
    html = '<iframe src="https://boards.greenhouse.io/embed/job_board?for=anthropic"></iframe>'
    assert sniff(html) == ("greenhouse", "anthropic")


def test_sniffs_greenhouse_plain_link():
    html = '<a href="https://boards.greenhouse.io/figma/jobs/12345">Apply</a>'
    assert sniff(html) == ("greenhouse", "figma")


def test_sniffs_lever():
    html = '<a href="https://jobs.lever.co/notion/abc-123">Senior PM</a>'
    assert sniff(html) == ("lever", "notion")


def test_sniffs_ashby():
    html = '<script>window.location="https://jobs.ashbyhq.com/ramp"</script>'
    assert sniff(html) == ("ashby", "ramp")


def test_sniffs_smartrecruiters():
    html = '<a href="https://careers.smartrecruiters.com/Postman">Careers</a>'
    assert sniff(html) == ("smartrecruiters", "Postman")


def test_sniffs_workday_and_builds_cxs_url():
    html = '<a href="https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced">Careers</a>'
    result = sniff(html)
    assert result is not None
    ats, cxs_url = result
    assert ats == "workday"
    assert cxs_url == "https://adobe.wd5.myworkdayjobs.com/wday/cxs/adobe/external_experienced/jobs"


def test_no_known_ats_returns_none():
    assert sniff("<html><body>Just a plain careers page</body></html>") is None
