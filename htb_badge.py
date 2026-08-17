#!/usr/bin/env python3
"""Generate a TryHackMe-style profile badge (SVG) from Hack The Box stats.

Usage:
    export HTB_APP_TOKEN=...
    python htb_badge.py <htb-username-or-profile-url>

Requires a free HTB "App Token" (create one on app.hackthebox.com under
account settings -> App Tokens). HTB's v4 API requires authentication even
to read another user's public profile.
"""

import argparse
import os
import re
import sys
from xml.sax.saxutils import escape

import requests

API_BASE = "https://labs.hackthebox.com/api/v4"
SITE_BASE = "https://www.hackthebox.com"
PROFILE_URL_RE = re.compile(r"hackthebox\.(?:com|eu)/(?:profile|users)/(\d+)")
CREDIT = "Made by fer"


def api_get(session, path, params=None):
    resp = session.get(f"{API_BASE}{path}", params=params, timeout=15)
    if resp.status_code == 401:
        raise SystemExit(
            "HTB avviste forespørselen (401 Unauthorized). "
            "Sjekk at HTB_APP_TOKEN er gyldig og ikke utløpt."
        )
    resp.raise_for_status()
    return resp.json()


def _iter_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_dicts(item)


def resolve_username_to_id(session, username):
    data = api_get(session, "/search/fetch", params={"query": username, "tags[]": "users"})
    name_keys = ("name", "value", "text", "username")

    matches = [
        d for d in _iter_dicts(data)
        if "id" in d and any(
            isinstance(d.get(k), str) and d[k].lower() == username.lower()
            for k in name_keys
        )
    ]
    if not matches:
        candidates = [d for d in _iter_dicts(data) if "id" in d and any(k in d for k in name_keys)]
        if len(candidates) == 1:
            matches = candidates

    if not matches:
        raise SystemExit(
            f"Kunne ikke slå opp bruker-ID for '{username}' automatisk "
            "(HTBs søke-API kan ha endret svarformat siden dette scriptet ble skrevet). "
            "Prøv i stedet å oppgi hele profil-lenken din, f.eks. "
            "https://app.hackthebox.com/profile/123456"
        )
    return int(matches[0]["id"])


def resolve_target(session, target):
    match = PROFILE_URL_RE.search(target)
    if match:
        return int(match.group(1))
    return resolve_username_to_id(session, target.strip().lstrip("@"))


def pick(d, *names, default=None):
    for name in names:
        value = d.get(name)
        if value is not None:
            return value
    return default


def normalize_avatar(avatar):
    if not avatar:
        return f"{SITE_BASE}/images/default-avatar.svg"
    if avatar.startswith("http"):
        return avatar
    return SITE_BASE + avatar


def fetch_profile(session, user_id):
    data = api_get(session, f"/user/profile/basic/{user_id}")
    profile = data.get("profile", data)

    missing = [
        key for key in ("name", "points", "user_owns", "system_owns")
        if pick(profile, key) is None
    ]
    if missing:
        print(
            f"Advarsel: feltene {missing} ble ikke funnet i HTB-responsen. "
            "HTB kan ha endret API-formatet - badgen vil bruke 0/ukjent for disse.",
            file=sys.stderr,
        )

    return {
        "name": pick(profile, "name", "username", default="unknown"),
        "rank": pick(profile, "rank", "rank_name", default="Unranked"),
        "points": int(pick(profile, "points", default=0) or 0),
        "ranking": pick(profile, "ranking", "rank_position", default=None),
        "user_owns": int(pick(profile, "user_owns", "userOwns", default=0) or 0),
        "system_owns": int(pick(profile, "system_owns", "systemOwns", default=0) or 0),
        "respects": int(pick(profile, "respects", "respect", default=0) or 0),
        "avatar": normalize_avatar(pick(profile, "avatar", "avatar_thumb")),
    }


# Minimal line-icon paths (Feather-icon style, 24x24 viewBox).
ICON_STAR = '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>'
ICON_FLAG = '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/>'
ICON_TREND = '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>'
ICON_USERS = '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'


def icon(path_data, x, y, size=16):
    scale = size / 24
    return (
        f'<g transform="translate({x},{y}) scale({scale})">'
        f'<g fill="none" stroke="#9FEF00" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f'{path_data}</g></g>'
    )


def stat_column(x, icon_svg, value, label):
    return f"""
    <g>
      {icon_svg}
      <text x="{x + 22}" y="{111}" font-family="Verdana, sans-serif" font-size="15" font-weight="bold" fill="#e6edf3">{escape(str(value))}</text>
      <text x="{x}" y="128" font-family="Verdana, sans-serif" font-size="8" letter-spacing="1" fill="#7d8590">{escape(label.upper())}</text>
    </g>"""


def build_svg(data):
    name = escape(str(data["name"]))
    rank = escape(str(data["rank"]))
    boxes_pwned = data["user_owns"] + data["system_owns"]
    ranking = data["ranking"]
    ranking_display = f"#{ranking:,}" if isinstance(ranking, int) else "N/A"

    # Lay out stat columns left-to-right, sizing each column to its own
    # content so large numbers (or long labels) never collide with the
    # next column - a fixed pixel step overflows for high point totals.
    columns = [
        (ICON_STAR, f'{data["points"]:,}', "Points"),
        (ICON_FLAG, str(boxes_pwned), "Pwned"),
        (ICON_TREND, ranking_display, "Rank"),
        (ICON_USERS, f'{data["respects"]:,}', "Respect"),
    ]
    stats_parts = []
    x = 130
    for icon_path, value, label in columns:
        stats_parts.append(stat_column(x, icon(icon_path, x, 96), value, label))
        col_width = max(len(str(value)) * 9.5, len(label) * 5.5) + 22
        x += col_width + 18
    stats = "".join(stats_parts)
    stats_end_x = x

    header_end_x = 130 + len(name) * 11.5 + 12 + (len(rank) * 7.5 + 16) + 12
    width = max(460, int(stats_end_x) + 20, int(header_end_x) + 20)
    height = 170

    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" role="img" aria-label="Hack The Box profile badge for {name}">
  <title>Hack The Box profile badge for {name}</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0d1117"/>
      <stop offset="100%" stop-color="#141d2b"/>
    </linearGradient>
    <pattern id="hex" width="22" height="19" patternUnits="userSpaceOnUse" patternTransform="translate(0,0)">
      <path d="M11 0 L22 6.3 L22 12.7 L11 19 L0 12.7 L0 6.3 Z" fill="none" stroke="#9FEF00" stroke-opacity="0.06" stroke-width="1"/>
    </pattern>
    <clipPath id="avatarClip">
      <circle cx="55" cy="75" r="35"/>
    </clipPath>
  </defs>

  <rect x="0.75" y="0.75" width="{width - 1.5}" height="{height - 1.5}" rx="14" fill="url(#bg)" stroke="#9FEF00" stroke-opacity="0.55" stroke-width="1.5"/>
  <rect x="0.75" y="0.75" width="{width - 1.5}" height="{height - 1.5}" rx="14" fill="url(#hex)"/>

  <circle cx="55" cy="75" r="37" fill="none" stroke="#9FEF00" stroke-width="2"/>
  <image href="{escape(data['avatar'])}" x="20" y="40" width="70" height="70" clip-path="url(#avatarClip)" preserveAspectRatio="xMidYMid slice"/>

  <text x="130" y="50" font-family="Verdana, sans-serif" font-size="20" font-weight="bold" fill="#e6edf3">{name}</text>
  <g transform="translate({130 + len(name) * 11.5 + 12},36)">
    <rect width="{len(rank) * 7.5 + 16}" height="20" rx="10" fill="#9FEF00" fill-opacity="0.12" stroke="#9FEF00" stroke-opacity="0.5"/>
    <text x="8" y="14" font-family="Verdana, sans-serif" font-size="11" fill="#9FEF00">{rank}</text>
  </g>

  <line x1="130" y1="68" x2="{width - 24}" y2="68" stroke="#9FEF00" stroke-opacity="0.2" stroke-width="1"/>

  {stats}

  <text x="24" y="{height - 16}" font-family="Verdana, sans-serif" font-size="10" fill="#7d8590">hackthebox.com</text>
  <text x="{width - 24}" y="{height - 16}" text-anchor="end" font-family="Verdana, sans-serif" font-size="10" font-style="italic" fill="#7d8590">{escape(CREDIT)}</text>
</svg>
"""


def main():
    parser = argparse.ArgumentParser(description="Generate an HTB profile badge (SVG).")
    parser.add_argument("target", help="HTB username or profile URL (e.g. https://app.hackthebox.com/profile/123456)")
    parser.add_argument("-o", "--output", default="assets/htb_badge.svg", help="Output SVG path")
    args = parser.parse_args()

    token = os.environ.get("HTB_APP_TOKEN")
    if not token:
        raise SystemExit(
            "Mangler HTB_APP_TOKEN. Opprett et gratis App Token på app.hackthebox.com "
            "(kontoinnstillinger -> App Tokens) og sett det som miljøvariabel:\n"
            "  export HTB_APP_TOKEN=...\n"
        )

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "htb-badge-generator (github.com/b0neng/htbbadge)",
    })

    user_id = resolve_target(session, args.target)
    profile = fetch_profile(session, user_id)
    svg = build_svg(profile)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(svg)

    print(f"Badge skrevet til {args.output} for bruker '{profile['name']}' (id={user_id}).")
    print(f"Profil-lenke: https://app.hackthebox.com/profile/{user_id}")


if __name__ == "__main__":
    main()
