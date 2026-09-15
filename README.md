# Job Search Agent

A daily-running tool that crawls a fixed list of target companies' career
sites (plus select aggregators), filters postings against a target title
list, applies location/remote and freshness rules, verifies each link is
live immediately before sending, and emails a digest — with no repeats of
previously-surfaced postings.

Implements the spec in full: Tier 1 ATS APIs (Greenhouse, Lever, Ashby,
SmartRecruiters, Workday), a Tier 2 direct-crawl fallback, Tier 3
aggregators (RemoteOK, We Work Remotely, Built In, Indeed), a strict
filter pipeline, SQLite-backed dedup, pre-send live-link verification, and
pluggable email delivery (SendGrid / Postmark / Gmail API). LinkedIn is
intentionally excluded — see "Why LinkedIn is excluded" below.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your email provider's credentials
```

### 1. Target companies

`config/companies.yaml` is pre-populated with 262 companies (from the
provided target list) as `tier2` entries, crawled directly at their
`careers_url` — this is what "search each careers site daily" runs against
out of the box, no further setup required to start.

Two things worth knowing:

- **121 companies from the source list had no `careers_url`** (things like
  Dribbble, Midjourney, Pentagram, A24) and are listed under `needs_url` in
  `config/companies.yaml` for reference only — the loader ignores that
  section. Add a `careers_url` and move an entry into `tier2` once you have
  one, and it'll be crawled on the next run.
- **Tier 2 crawling is a plain HTTP fetch, not a browser.** It reads
  server-rendered HTML (or embedded schema.org `JobPosting` structured
  data, which it prefers when present — see "Known limitations"). A
  careers page that renders its job list client-side via JS after load
  will come back empty here even though it's "live" in a real browser.
  For any company that's consistently returning nothing, it's very likely
  actually running on Greenhouse/Lever/Ashby/SmartRecruiters/Workday under
  the hood (common for startups in this list — e.g. Anthropic, Ramp,
  Notion, Vercel, Linear, Mercury). Run:

  ```bash
  python -m job_search_agent.discover_ats "Company Name"
  ```

  to check, then move the entry from `tier2` to the matching ATS section
  in `config/companies.yaml` with the discovered `slug` — Tier 1 is far
  more reliable (a real API, a real posted date) than the Tier 2 fallback.
  For Workday, check browser devtools' Network tab (filter "cxs") — see
  `job_search_agent/ats/workday.py` for the exact pattern to look for.

Re-check monthly with `python -m job_search_agent.recheck_ats` in case a
company migrates platforms or a Tier 2 page's markup changes (see "Error
Handling / Etiquette" in the original spec).

**Note on exclusions:** in addition to the spec's Not Interested list
(Meta, X, Snap, TikTok/ByteDance, AKQA, Allbirds, TKO Group), LinkedIn's
own careers page and CapCut (a ByteDance property) are excluded too —
LinkedIn per the spec's standing rule, CapCut as a reasonable extension of
the ByteDance exclusion. Flag it if that's not what you want.

### 2. Adjust titles and settings

- `config/titles.yaml` — target titles and the fuzzy-match threshold.
- `config/settings.yaml` — lookback window, accepted onsite metros
  (defaults to Portland-area), rate limiting, which aggregators to query,
  and email provider selection.

### 3. Run it

```bash
python -m job_search_agent.main            # one run, right now
python -m job_search_agent.scheduler --now  # same, via the scheduler module
python -m job_search_agent.scheduler        # keep running, fire daily at 07:00 local
python -m job_search_agent.scheduler --at 06:30
```

Or use real cron instead of keeping a process alive — see
`cron/job_search_agent.cron.example`.

## Pipeline

1. **Crawl** every configured company (Tier 1 API or Tier 2 fallback) plus
   the enabled Tier 3 aggregators.
2. **Filter**, in order: title match → company match (or "Not Interested"
   exclusion) → freshness (default 7-day lookback; no date = excluded,
   never included-with-caveat) → location/remote (explicit remote or an
   accepted onsite metro; ambiguous locations are flagged for manual
   review, never guessed).
3. **Dedup** against `data/seen_postings.sqlite3` (gitignored).
4. **Verify** every surviving posting is still live, right before sending
   — never from a cached crawl.
5. **Email** the digest, grouped by company. Zero new postings still sends
   a short "no new matches today" note, so silence is never mistaken for
   the tool being broken.
6. Only after a successful send are postings recorded as "seen."

## Why LinkedIn is excluded

Manual testing during spec development found LinkedIn blocks automated
fetching via `robots.txt`, and its search-result links/snippets don't
reliably reflect current listing status (one tested link redirected to a
generic search page; separately, a job manually verified was still
surfacing five months after its actual post date). It is not implemented
here and should not be added.

## Known limitations

- **Tier 2 / aggregator scraping is best-effort.** Where a page embeds
  schema.org `JobPosting` structured data (`job_search_agent/jsonld.py`),
  that's used for a genuine machine-readable date. Where it doesn't, Tier 2
  falls back to heuristic anchor/text parsing and is flagged
  `date_confidence: low`.
- **Live-link verification is a plain HTTP fetch, not a headless browser.**
  A page that only 404s after client-side JS runs can still pass. There's
  no cheap fix for that without a browser-automation dependency.
- **Indeed's `robots.txt` blocks most automated fetching of search
  results.** The Indeed fetcher respects that (as it should), so it will
  frequently return nothing — that's correct behavior per the spec's
  crawler etiquette rules, not a bug.
- **121 companies still need a `careers_url`** before they can be crawled
  at all — see `needs_url` in `config/companies.yaml` and the note above.

## Tests

```bash
pip install pytest
pytest tests/
```
