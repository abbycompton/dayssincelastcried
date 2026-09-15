"""Tier 3 aggregators: supplementary sources, not primary.

LinkedIn is deliberately not implemented here and must never be added: it
disallows automated fetching via robots.txt, and manual testing showed its
listing links/snippets don't reliably reflect current posting status (see
top-level spec notes). Any future contributor tempted to add it should read
those notes first.
"""
