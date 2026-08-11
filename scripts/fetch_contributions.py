#!/usr/bin/env python3
"""
Scrape real daily contribution counts from GitHub and write data/contributions.json
with the raw days plus derived stats (current streak, longest streak, best day,
monthly totals).

If a GitHub token is available, use the GraphQL API to fetch the user's full
contribution calendar. Otherwise fall back to public HTML scraping.
Run daily by .github/workflows/update-profile-art.yml.
"""
import datetime
import json
import os
import re
import sys

import requests
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(ROOT, "config.json")

with open(CONFIG_PATH) as fh:
    CONFIG = json.load(fh)

USERNAME = (
    os.environ.get("GH_PROFILE_USER")
    or os.environ.get("GITHUB_REPOSITORY_OWNER")
    or CONFIG["github_username"]
)
URL = f"https://github.com/users/{USERNAME}/contributions"
GITHUB_API_URL = "https://api.github.com/graphql"
GH_PROFILE_TOKEN = os.environ.get("GH_PROFILE_TOKEN")
TOKEN = (
    GH_PROFILE_TOKEN
    or os.environ.get("GITHUB_TOKEN")
    or os.environ.get("GH_TOKEN")
)
OUT_PATH = os.path.join(ROOT, CONFIG["assets"]["contributions_data"])


def fetch_days_graphql():
    now = datetime.datetime.now(datetime.timezone.utc)
    end_date = now.date()
    start_date = end_date - datetime.timedelta(days=364)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """
    variables = {
        "login": USERNAME,
        "from": f"{start_date.isoformat()}T00:00:00Z",
        "to": f"{end_date.isoformat()}T23:59:59Z",
    }
    headers = {
        "User-Agent": "profile-readme-bot/1.0",
        "Accept": "application/json",
    }
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN or GH_TOKEN is required for GitHub GraphQL fetch")
    headers["Authorization"] = f"Bearer {TOKEN}"
    resp = requests.post(GITHUB_API_URL, json={"query": query, "variables": variables}, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errors"):
        print(json.dumps(payload["errors"], indent=2), file=sys.stderr)
        raise RuntimeError("GitHub GraphQL returned errors")
    user = payload.get("data", {}).get("user")
    if not user:
        raise RuntimeError("GitHub GraphQL response missing user data")
    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    days = []
    for week in weeks:
        for day in week["contributionDays"]:
            days.append({"date": day["date"], "count": day["contributionCount"]})
    days.sort(key=lambda d: d["date"])
    return days


def fetch_days_scrape():
    resp = requests.get(URL, headers={"User-Agent": "profile-readme-bot/1.0"}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    cells = soup.select("td.ContributionCalendar-day")
    if not cells:
        print("no calendar cells found -- github markup may have changed", file=sys.stderr)
        sys.exit(1)

    days = []
    for td in cells:
        date = td.get("data-date")
        if not date:
            continue
        td_id = td.get("id")
        tooltip_el = soup.find("tool-tip", attrs={"for": td_id}) if td_id else None
        text = tooltip_el.get_text(strip=True) if tooltip_el else ""
        if re.search(r"no contributions", text, re.I):
            count = 0
        else:
            m = re.match(r"(\d+)", text)
            count = int(m.group(1)) if m else 0
        days.append({"date": date, "count": count})

    days.sort(key=lambda d: d["date"])
    return days


def fetch_days():
    if TOKEN:
        print("fetching contribution data via GitHub GraphQL API", file=sys.stderr)
        try:
            return fetch_days_graphql()
        except Exception as exc:
            print(f"GitHub GraphQL fetch failed: {exc}", file=sys.stderr)
            print("falling back to public HTML scraping", file=sys.stderr)
    return fetch_days_scrape()


def compute_current_streak(days):
    idx = len(days) - 1
    if days[idx]["count"] == 0:
        idx -= 1  # today isn't over yet -- don't break the streak on it
    streak = 0
    end_idx = idx
    while idx >= 0 and days[idx]["count"] > 0:
        streak += 1
        idx -= 1
    start_idx = idx + 1
    if streak == 0:
        return 0, None, None
    return streak, days[start_idx]["date"], days[end_idx]["date"]


def compute_longest_streak(days):
    longest = run = 0
    longest_start = longest_end = None
    run_start_idx = None
    for i, d in enumerate(days):
        if d["count"] > 0:
            if run == 0:
                run_start_idx = i
            run += 1
            if run > longest:
                longest = run
                longest_start = days[run_start_idx]["date"]
                longest_end = days[i]["date"]
        else:
            run = 0
    return longest, longest_start, longest_end


def build_data(days):
    total = sum(d["count"] for d in days)
    active_days = sum(1 for d in days if d["count"] > 0)
    best = max(days, key=lambda d: d["count"])
    cur_len, cur_start, cur_end = compute_current_streak(days)
    long_len, long_start, long_end = compute_longest_streak(days)

    monthly = {}
    for d in days:
        key = d["date"][:7]
        monthly[key] = monthly.get(key, 0) + d["count"]
    monthly_list = [{"month": k, "total": v} for k, v in sorted(monthly.items())]

    return {
        "username": USERNAME,
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "range": {"start": days[0]["date"], "end": days[-1]["date"]},
        "total_contributions": total,
        "active_days": active_days,
        "avg_per_active_day": round(total / active_days, 1) if active_days else 0,
        "current_streak": {"length": cur_len, "start": cur_start, "end": cur_end},
        "longest_streak": {"length": long_len, "start": long_start, "end": long_end},
        "best_day": {"date": best["date"], "count": best["count"]},
        "monthly": monthly_list,
        "days": days,
    }


if __name__ == "__main__":
    days = fetch_days()
    data = build_data(days)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"wrote {OUT_PATH}: {data['total_contributions']} contributions, "
          f"current streak {data['current_streak']['length']}, "
          f"longest streak {data['longest_streak']['length']}")
