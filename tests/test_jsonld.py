from bs4 import BeautifulSoup

from job_search_agent.jsonld import extract_job_postings

SAMPLE_HTML = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "Senior Program Manager",
  "datePosted": "2026-09-10T00:00:00Z",
  "hiringOrganization": {"@type": "Organization", "name": "Figma"},
  "jobLocation": {"@type": "Place", "address": {"addressLocality": "Remote", "addressRegion": ""}},
  "url": "https://example.com/jobs/1"
}
</script>
</head><body></body></html>
"""


def test_extracts_job_posting_from_jsonld():
    soup = BeautifulSoup(SAMPLE_HTML, "lxml")
    postings = extract_job_postings(soup, source="test")
    assert len(postings) == 1
    posting = postings[0]
    assert posting.title == "Senior Program Manager"
    assert posting.company == "Figma"
    assert posting.date_confidence == "high"
    assert posting.posted_at is not None


def test_no_jsonld_returns_empty():
    soup = BeautifulSoup("<html><body>no jobs here</body></html>", "lxml")
    assert extract_job_postings(soup, source="test") == []
