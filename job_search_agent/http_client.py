"""Shared HTTP helpers: per-domain rate limiting, robots.txt checks, and error logging."""

from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

USER_AGENT = "JobSearchAgent/0.1 (personal job-search digest; contact: yeakel.abby@gmail.com)"

logger = logging.getLogger("job_search_agent")


class RateLimiter:
    """Enforces a minimum delay between requests to the same domain."""

    def __init__(self, seconds_per_domain: float = 1.0):
        self.seconds_per_domain = seconds_per_domain
        self._last_request: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str) -> None:
        domain = urlparse(url).netloc
        with self._lock:
            last = self._last_request.get(domain, 0.0)
            now = time.monotonic()
            elapsed = now - last
            if elapsed < self.seconds_per_domain:
                time.sleep(self.seconds_per_domain - elapsed)
            self._last_request[domain] = time.monotonic()


_robots_cache: dict[str, RobotFileParser] = {}


def robots_allowed(url: str, user_agent: str = USER_AGENT) -> bool:
    """Checks robots.txt for the given URL's domain. Fails open (allowed) only
    if robots.txt can't be fetched at all, per common crawler etiquette; an
    explicit Disallow always blocks."""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    rp = _robots_cache.get(base)
    if rp is None:
        rp = RobotFileParser()
        rp.set_url(f"{base}/robots.txt")
        try:
            rp.read()
        except Exception:
            logger.warning("Could not fetch robots.txt for %s; proceeding cautiously", base)
        _robots_cache[base] = rp
    try:
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True


class HttpClient:
    """Thin wrapper around requests that applies rate limiting, a UA string,
    and consistent timeout/error handling used by every crawler/aggregator."""

    def __init__(self, rate_limiter: RateLimiter, timeout: int = 15):
        self.rate_limiter = rate_limiter
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def get(self, url: str, respect_robots: bool = False, **kwargs) -> requests.Response | None:
        if respect_robots and not robots_allowed(url):
            logger.info("robots.txt disallows fetching %s; skipping", url)
            return None
        self.rate_limiter.wait(url)
        try:
            resp = self.session.get(url, timeout=self.timeout, **kwargs)
            return resp
        except requests.RequestException as exc:
            logger.error("HTTP GET failed for %s: %s", url, exc)
            return None

    def post(self, url: str, **kwargs) -> requests.Response | None:
        self.rate_limiter.wait(url)
        try:
            return self.session.post(url, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            logger.error("HTTP POST failed for %s: %s", url, exc)
            return None
