"""Merges filled-in careers URLs back into config/companies.yaml.

The companion to config/careers_urls_todo.txt: that file lists every
company currently missing (or only guessed at) a careers_url, one per
line, as "Company Name | https://example.com/careers". Fill in as many
URLs as you know, leave the rest blank, and run this against the file (or
paste the same lines directly).

Usage:
    python -m job_search_agent.apply_careers_urls config/careers_urls_todo.txt
    python -m job_search_agent.apply_careers_urls --apply config/careers_urls_todo.txt

Without --apply it's a dry run that just prints what would change.

Matching is by company name against both `needs_url` and `tier2` (so this
also works to correct/replace an existing AI-guessed tier2 URL, not just
fill in a blank one). A line naming a company not found in either section
is reported and skipped rather than silently ignored.
"""

from __future__ import annotations

import argparse
import sys

import yaml

from . import config as config_module


def parse_lines(text: str) -> dict[str, str]:
    """Returns {company_name: careers_url} for every non-blank, well-formed
    "Name | URL" line. Lines starting with # (comments) and blank/malformed
    lines are ignored."""
    updates = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        name, _, url = line.partition("|")
        name = name.strip()
        url = url.strip()
        if name and url:
            updates[name] = url
    return updates


def apply_updates(config_path, updates: dict[str, str]) -> tuple[list[str], list[str]]:
    """Returns (applied_names, not_found_names). Moves a matched needs_url
    entry into tier2 with the given careers_url (dropping any `note`); for a
    name already in tier2, just overwrites its careers_url and clears any
    `verified: false` flag, since a user-supplied URL isn't a guess."""
    with open(config_path) as f:
        data = yaml.safe_load(f)

    needs_url_by_name = {e["name"]: e for e in data.get("needs_url", [])}
    tier2_by_name = {e["name"]: e for e in data.get("tier2", [])}

    applied = []
    not_found = []

    for name, url in updates.items():
        if name in needs_url_by_name:
            entry = needs_url_by_name.pop(name)
            data["needs_url"] = [e for e in data.get("needs_url", []) if e["name"] != name]
            data.setdefault("tier2", []).append({
                "name": name,
                "ats": "tier2",
                "careers_url": url,
                "category": entry.get("category"),
            })
            applied.append(name)
        elif name in tier2_by_name:
            entry = tier2_by_name[name]
            entry["careers_url"] = url
            entry.pop("verified", None)
            applied.append(name)
        else:
            not_found.append(name)

    with open(config_path, "w") as f:
        yaml.dump(data, f, sort_keys=False, allow_unicode=True, width=100)

    return applied, not_found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", help="Path to a file of 'Company Name | URL' lines.")
    parser.add_argument("--apply", action="store_true", help="Write the changes (default: dry run, just prints).")
    args = parser.parse_args()

    with open(args.file) as f:
        text = f.read()

    updates = parse_lines(text)
    if not updates:
        print("No 'Name | URL' lines found (need a non-blank name and URL on both sides of a '|').")
        return

    print(f"Found {len(updates)} filled-in URL(s):")
    for name, url in updates.items():
        print(f"  - {name}: {url}")

    if not args.apply:
        print("\nDry run only -- re-run with --apply to write these into config/companies.yaml.")
        return

    config_path = config_module.CONFIG_DIR / "companies.yaml"
    applied, not_found = apply_updates(config_path, updates)

    print(f"\nApplied {len(applied)} update(s) to config/companies.yaml.")
    if not_found:
        print(f"{len(not_found)} name(s) not found in needs_url or tier2 (typo, or already resolved?):")
        for name in not_found:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
