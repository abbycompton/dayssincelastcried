# Job Search Agent

A daily-running tool that crawls a fixed list of target companies' career
sites (plus select aggregators), filters postings against a target title
list, applies location/remote and freshness rules, verifies each link is
live immediately before sending, and emails a digest — with no repeats of
previously-surfaced postings.

Implements the spec in full: Tier 1 ATS APIs (Greenhouse, Lever, Ashby,
SmartRecruiters, Workday), a Tier 2 direct-crawl fallback (with a
headless-render fallback and automatic ATS detection so it doesn't quietly
come back empty on JS-heavy pages — see "How Tier 2 avoids blank results"),
Tier 3 aggregators (RemoteOK, We Work Remotely, Built In, Indeed), a strict
filter pipeline, SQLite-backed dedup, pre-send live-link verification, and
pluggable email delivery (SendGrid / Postmark / Gmail API). LinkedIn is
intentionally excluded — see "Why LinkedIn is excluded" below.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # optional but recommended -- see below
cp .env.example .env          # fill in your email provider's credentials
```

The `playwright install chromium` step downloads a headless browser used
only as a fallback when a Tier 2 careers page's job list is rendered by
client-side JS (a plain HTTP fetch can't see that). It's optional — if you
skip it, everything else still works, that fallback just won't fire, and
a JS-heavy page's postings will get logged as an unusual all-zero result
(see below) instead of being found.

### 1. Target companies

`config/companies.yaml` is pre-populated with 321 companies (from the
provided target lists, plus some best-effort URLs filled in — see below) as
`tier2` entries, crawled directly at their `careers_url` — this is what
"search each careers site daily" runs against out of the box, no further
setup required to start.

Worth knowing:

- **~90 companies from the source lists still have no usable `careers_url`**
  (Midjourney, several small agencies and foundations, recently-acquired or
  wound-down companies like Cruise and Simple, ambiguous names like "Aura").
  They're listed under `needs_url` in `config/companies.yaml`, each with a
  `note` explaining why it's unresolved (acquired, defunct, ambiguous name,
  no known public careers page, etc.) — the loader ignores this section.

  **`config/careers_urls_todo.txt` is the easy way to fill these in.** It's
  a plain-text list, one company per line as `Company Name | ` — add a URL
  after the `|` for any you know and leave the rest blank. Then either run:

  ```bash
  python -m job_search_agent.apply_careers_urls --apply config/careers_urls_todo.txt
  ```

  to merge it into `config/companies.yaml` yourself, or just paste your
  edited lines back in chat and it'll get merged for you. The same file/tool
  also works to *correct* an existing best-effort `tier2` URL — a line for a
  company already in `tier2` overwrites its URL instead of adding a
  duplicate. Regenerate the todo file at any time to reflect whatever's
  still outstanding (whatever's left in `needs_url`).
- **58 of the 321 `tier2` URLs were filled in from training knowledge, not
  fetched or verified** (this environment has no general internet access —
  confirmed by testing, both plain HTTP and a headless browser get a
  proxy-level connection block on arbitrary domains). They're standard
  `/careers`-style guesses for companies I'm reasonably confident are still
  active, but some may be wrong or stale. A wrong one fails safe: it shows
  up as an HTTP-failure or all-zero-postings line in `logs/errors.log` on
  the first real run (see below), not a silent bad result.
- **Tier 2 crawling now retries through a headless browser and looks for an
  embedded ATS board when the plain fetch finds nothing** — see the next
  section — so most JS-rendered pages should self-correct without any
  manual discovery step. For the ones that still come back empty, or to
  permanently upgrade a company to a faster/more reliable Tier 1 API
  instead of re-detecting it every day, run:

  ```bash
  python -m job_search_agent.bulk_upgrade --apply
  ```

Re-check monthly with `python -m job_search_agent.recheck_ats` in case a
company migrates platforms or a Tier 2 page's markup changes (see "Error
Handling / Etiquette" in the original spec).

**Note on exclusions:** in addition to the spec's Not Interested list
(Meta, X, Snap, TikTok/ByteDance, AKQA, Allbirds, TKO Group), LinkedIn's
own careers page and CapCut (a ByteDance property) are excluded too —
LinkedIn per the spec's standing rule, CapCut as a reasonable extension of
the ByteDance exclusion. Flag it if that's not what you want.

## How Tier 2 avoids blank results

A plain HTTP fetch can't run JavaScript, so a careers page that builds its
job list client-side (common on modern marketing-site-wraps-a-job-board
setups) looks empty to `requests` even though it's full of postings in a
real browser. Three things address this, in order, inside
`job_search_agent/tier2_crawler.py`:

1. **Structured data first.** If the page embeds schema.org `JobPosting`
   JSON-LD, that's used directly — it's genuinely machine-readable and
   comes with a real date, regardless of how the visible page renders.
2. **ATS sniffing (`ats_sniff.py`).** If the page's HTML contains a link or
   iframe pointing at a known Greenhouse/Lever/Ashby/SmartRecruiters/
   Workday board, that's fetched directly instead of parsing the wrapper
   page's text — this is what usually happens for companies whose
   marketing site just embeds their real job board.
3. **Headless-render fallback (`render.py`, needs `playwright install
   chromium`).** If nothing was found in the static HTML at all, the same
   page is re-fetched through a real headless Chromium tab so client-side
   rendering gets a chance to run, then steps 1–2 are retried on the
   rendered DOM.

If a company still returns zero postings after all three, that's logged as
a distinct warning (`logs/errors.log`) explaining it's likely a stale URL,
a robots.txt block, or a page structure the crawler doesn't recognize —
**not** presented the same as "no open roles today," so a structurally
broken source doesn't quietly and permanently disappear from your digest.
`python -m job_search_agent.recheck_ats` runs this same check for every
configured company on demand; `python -m job_search_agent.bulk_upgrade`
scans specifically for step-2 ATS matches worth promoting to Tier 1
permanently.

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

## Run reports

Every run (`python -m job_search_agent.main`) writes a report to
`logs/run_report_<date>.{json,md}` (and `logs/latest_run_report.{json,md}`,
overwritten each time) — separate from the job digest email. The digest
answers "what's new"; this answers "how's the crawl doing": which
companies came back empty and why (HTTP failure, robots.txt block, a
structurally-empty page — the same reasoning `tier2_crawler` already logs,
just collected in one place), plus the funnel from raw postings crawled
through filtered, deduped, and verified. Check the Markdown version daily
alongside the digest; the JSON version is there if you want to graph
trends over time or feed it into something else.

## Testing without hitting real company sites

```bash
python -m job_search_agent.smoke_test
```

Spins up a throwaway HTTP server on localhost serving a handful of fake
"companies" that exercise every code path in the crawl pipeline — a
JSON-LD page, a plain-HTML anchor-heuristic page, a page that only renders
its listings via JavaScript (proving the headless-render fallback actually
works), an HTTP 500, an HTTP 404, and a page embedding a fake ATS board
(proving ATS-sniffing fires, even though the handoff itself will fail
without real network access to the real ATS). Runs the real crawl → filter
→ dedup → verify → report pipeline against them and prints the resulting
report and a sample digest. No rate limits, no external network, safe to
run anytime as a fast regression check — useful for confirming a code
change didn't break anything before pointing it at the real 300+ companies.

It is not a substitute for a real run: the fixtures are hand-built to hit
specific code paths, not representative of any real company's site.

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
- **The headless-render fallback only fires when the static pass finds
  literally nothing.** A page that returns *some* markup-level content but
  not the real job listings (e.g. a loading skeleton with unrelated text)
  won't trigger it. It's also only attempted once per company per run, with
  a fixed post-load wait rather than waiting for a specific element — a
  slow-hydrating page could still come back empty.
- **Live-link verification is a plain HTTP fetch, not a headless browser.**
  A page that only 404s after client-side JS runs can still pass. There's
  no cheap fix for that without a browser-automation dependency.
- **Indeed's `robots.txt` blocks most automated fetching of search
  results.** The Indeed fetcher respects that (as it should), so it will
  frequently return nothing — that's correct behavior per the spec's
  crawler etiquette rules, not a bug.
- **90 companies still need a `careers_url`** before they can be crawled at
  all, and 58 more have an unverified best-effort one — see `needs_url` in
  `config/companies.yaml`, `config/careers_urls_todo.txt`, and the notes
  above.

## Tests

```bash
pip install pytest
pytest tests/
```
