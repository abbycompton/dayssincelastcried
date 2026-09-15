"""Headless-browser rendering fallback for Tier 2 crawling.

A plain HTTP fetch + BeautifulSoup can't see content a page builds via
client-side JavaScript after load -- common on modern SPA-style careers
pages (a React/Vue job board embedded in a marketing site, or one that
pulls listings from an XHR call after mount). When the static pass in
tier2_crawler finds nothing, it retries through here: a real headless
Chromium tab that runs the page's JS and hands back the rendered DOM.

Optional dependency. Needs:
    pip install playwright
    playwright install chromium
If Playwright or its browser isn't available, rendering is silently
skipped and callers fall back to whatever the static pass found -- a
missing optional dependency should never break a daily crawl run.
"""

from __future__ import annotations

import logging
import os

from .http_client import USER_AGENT, RateLimiter

logger = logging.getLogger("job_search_agent")

try:
    from playwright.sync_api import sync_playwright

    _PLAYWRIGHT_IMPORTABLE = True
except ImportError:
    _PLAYWRIGHT_IMPORTABLE = False

# This repo's own dev/CI sandbox ships a pre-installed Chromium at a fixed
# path (see PLAYWRIGHT_BROWSERS_PATH); a user's own machine installs it via
# `playwright install chromium` instead, in which case Playwright resolves
# the binary itself and this stays None.
_PINNED_EXECUTABLE = "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None


class Renderer:
    """Wraps one browser instance across an entire crawl run -- launching a
    fresh browser per page would dominate a 200+ company daily run.

    Usage:
        with Renderer(rate_limiter) as renderer:
            html = renderer.render(url)  # None if unavailable or it failed
    """

    def __init__(self, rate_limiter: RateLimiter, timeout_ms: int = 20000):
        self.rate_limiter = rate_limiter
        self.timeout_ms = timeout_ms
        self.available = _PLAYWRIGHT_IMPORTABLE
        self._playwright = None
        self._browser = None

    def __enter__(self) -> "Renderer":
        if not self.available:
            logger.info(
                "[render] Playwright not installed; JS-rendering fallback disabled "
                "for this run (pip install playwright && playwright install chromium)"
            )
            return self
        try:
            self._playwright = sync_playwright().start()
            launch_kwargs = {"headless": True}
            if _PINNED_EXECUTABLE:
                launch_kwargs["executable_path"] = _PINNED_EXECUTABLE
            self._browser = self._playwright.chromium.launch(**launch_kwargs)
        except Exception:
            logger.warning(
                "[render] could not launch headless Chromium; JS-rendering fallback "
                "disabled for this run (playwright install chromium?)",
                exc_info=True,
            )
            self.available = False
        return self

    def __exit__(self, *_exc) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def render(self, url: str) -> str | None:
        if not self.available or self._browser is None:
            return None

        self.rate_limiter.wait(url)
        page = None
        try:
            page = self._browser.new_page(user_agent=USER_AGENT)
            page.goto(url, timeout=self.timeout_ms, wait_until="load")
            # Give client-side hydration a beat to fetch and mount job
            # listings after the initial load event -- "load" alone often
            # fires before an SPA's own data fetch resolves.
            page.wait_for_timeout(2000)
            return page.content()
        except Exception as exc:
            logger.warning("[render] failed to render %s: %s", url, exc)
            return None
        finally:
            if page is not None:
                page.close()
