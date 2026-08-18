#!/usr/bin/env python3
"""Generate a TryHackMe-style profile badge (SVG) from Hack The Box stats.

Usage:
    python htb_badge.py <htb-username-or-profile-url>

Requires a free HTB "App Token" (create one on app.hackthebox.com under
account settings -> App Tokens). HTB's v4 API requires authentication even
to read another user's public profile. Set it via the HTB_APP_TOKEN
environment variable, or the script will prompt for it (hidden input).
"""

import argparse
import base64
import getpass
import json
import os
import re
import subprocess
import sys
from xml.sax.saxutils import escape

import requests

API_BASE = "https://labs.hackthebox.com/api/v4"
SITE_BASE = "https://www.hackthebox.com"
PROFILE_URL_RE = re.compile(r"hackthebox\.(?:com|eu)/(?:profile|users)/(\d+)")
CREDIT = "Made by fer"
DEBUG_FILE = "debug_response.json"

DEBUG = False
_debug_data = {}


def debug_save(label, data):
    if not DEBUG:
        return
    _debug_data[label] = data
    with open(DEBUG_FILE, "w", encoding="utf-8") as f:
        json.dump(_debug_data, f, indent=2)


def api_get(session, path, params=None, debug_label=None):
    resp = session.get(f"{API_BASE}{path}", params=params, timeout=15)
    if resp.status_code == 401:
        raise SystemExit(
            "HTB rejected the request (401 Unauthorized). "
            "Check that HTB_APP_TOKEN is valid and hasn't expired."
        )
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        if DEBUG:
            print(f"[debug] {resp.status_code} response body: {resp.text[:2000]}", file=sys.stderr)
        raise
    data = resp.json()
    if debug_label:
        debug_save(debug_label, data)
    return data


def _iter_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_dicts(item)


def resolve_username_to_id(session, username):
    data = api_get(
        session, "/search/fetch",
        params={"query": username, "tags[]": "users"},
        debug_label="search_fetch",
    )
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
            f"Could not automatically resolve a user ID for '{username}' "
            "(HTB's search API may have changed its response format since this "
            "script was written). Try passing your full profile URL instead, "
            "e.g. https://app.hackthebox.com/profile/123456"
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
        return None
    if avatar.startswith("http"):
        return avatar
    return SITE_BASE + avatar


def fetch_avatar_data_uri(avatar_url):
    """Download the avatar and embed it as a data URI so the badge doesn't
    depend on GitHub being able to hotlink an external HTB image at render
    time (HTB's CDN may reject requests from GitHub's image proxy).

    Uses a plain, unauthenticated request rather than the HTB API session:
    avatars are served from a separate host (e.g. an S3 bucket), and
    forwarding the HTB Authorization header there gets rejected with a
    400 Bad Request instead of just being ignored."""
    if not avatar_url:
        return None
    try:
        resp = requests.get(
            avatar_url, timeout=15,
            headers={"User-Agent": "htb-badge-generator (github.com/b0neng/htbbadge)"},
        )
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/png").split(";")[0].strip()
        if not content_type.startswith("image/"):
            content_type = "image/png"
        encoded = base64.b64encode(resp.content).decode("ascii")
        return f"data:{content_type};base64,{encoded}"
    except requests.RequestException as e:
        print(f"Warning: could not download avatar ({e}). Using a placeholder icon instead.", file=sys.stderr)
        return None


#  Fields worth showing in --debug output: enough to diagnose stat mapping
# (rank/level naming, points, owns, followers) without printing PII the
# profile response also contains (full_name, phone_number, timezone, ...).
SAFE_DEBUG_FIELDS = (
    "name", "rank", "rank_id", "next_rank", "next_rank_points",
    "current_rank_progress", "points", "ranking", "user_owns",
    "system_owns", "followed_by_count",
)


def fetch_profile(session, user_id):
    data = api_get(session, f"/user/profile/basic/{user_id}", debug_label="profile_basic")
    profile = data.get("profile", data)

    if DEBUG:
        print(f"[debug] profile keys: {sorted(profile.keys())}", file=sys.stderr)
        safe_values = {k: profile[k] for k in SAFE_DEBUG_FIELDS if k in profile}
        print(f"[debug] known field values: {safe_values}", file=sys.stderr)
        level_like = {k: v for k, v in profile.items() if "level" in k.lower() or "xp" in k.lower()}
        if level_like:
            print(f"[debug] possible level/XP fields: {level_like}", file=sys.stderr)

    missing = [
        key for key in ("name", "points", "user_owns", "system_owns")
        if pick(profile, key) is None
    ]
    if missing:
        print(
            f"Warning: fields {missing} were not found in the HTB response. "
            "HTB may have changed its API format - the badge will show 0/unknown for these. "
            "Re-run with --debug to inspect the raw response.",
            file=sys.stderr,
        )

    return {
        "name": pick(profile, "name", "username", default="unknown"),
        "rank": pick(profile, "rank", "rank_name", default="Unranked"),
        "points": int(pick(profile, "points", default=0) or 0),
        "ranking": pick(profile, "ranking", "rank_position", default=None),
        "user_owns": int(pick(profile, "user_owns", "userOwns", default=0) or 0),
        "system_owns": int(pick(profile, "system_owns", "systemOwns", default=0) or 0),
        "level": pick(profile, "level", "user_level", "current_level", "xp_level", default=None),
        "avatar": normalize_avatar(pick(profile, "avatar", "avatar_thumb")),
    }


# Minimal line-icon paths (Feather-icon style, 24x24 viewBox).
ICON_STAR = '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>'
ICON_FLAG = '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/>'
ICON_TREND = '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>'
ICON_LEVEL = '<circle cx="12" cy="8" r="7"/><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"/>'

AVATAR_FALLBACK = (
    '<rect x="20" y="40" width="70" height="70" fill="#2d3746" clip-path="url(#avatarClip)"/>'
    '<circle cx="55" cy="67" r="14" fill="#6e7f96" clip-path="url(#avatarClip)"/>'
    '<circle cx="55" cy="115" r="26" fill="#6e7f96" clip-path="url(#avatarClip)"/>'
)


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


def build_svg(data, avatar_data_uri=None):
    name = escape(str(data["name"]))
    rank = escape(str(data["rank"]))
    # A machine only counts as "pwned" once both flags are captured, so
    # this is min() rather than a sum of the two flag counts (confirmed
    # against a real profile: user_owns=5, system_owns=4 -> 4 machines
    # fully owned, matching HTB's own "Machines" counter).
    boxes_pwned = min(data["user_owns"], data["system_owns"])
    ranking = data["ranking"]
    ranking_display = f"#{ranking:,}" if isinstance(ranking, int) else "N/A"
    level = data["level"]
    level_display = f"Lvl {level}" if isinstance(level, (int, float)) else "N/A"

    # Lay out stat columns left-to-right, sizing each column to its own
    # content so large numbers (or long labels) never collide with the
    # next column - a fixed pixel step overflows for high point totals.
    columns = [
        (ICON_STAR, f'{data["points"]:,}', "Points"),
        (ICON_FLAG, str(boxes_pwned), "Pwned"),
        (ICON_TREND, ranking_display, "Rank"),
        (ICON_LEVEL, level_display, "Level"),
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

    avatar_svg = (
        f'<image href="{escape(avatar_data_uri)}" x="20" y="40" width="70" height="70" '
        f'clip-path="url(#avatarClip)" preserveAspectRatio="xMidYMid slice"/>'
        if avatar_data_uri else AVATAR_FALLBACK
    )

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
  {avatar_svg}

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


LEVEL_ENDPOINT_CANDIDATES = (
    "/user/profile/activity/{id}",
    "/season/user/profile/{id}",
    "/user/profile/season/{id}",
    "/user/profile/graph/activity/{id}",
    "/user/profile/chart/{id}",
)


def probe_level_endpoints(session, user_id):
    """--debug only: HTB's newer Level/XP system (shown on the profile page
    as e.g. "Apprentice, Lvl 18") isn't present anywhere in
    /user/profile/basic - it's a different system from the rank/rank_id
    fields that endpoint returns (the classic Noob/Script Kiddie/.../
    Omniscient ranks). Try a handful of plausible endpoints for it and
    report what's actually there, since this can't be verified without
    a live, authenticated HTB session."""
    print("\n[debug] probing candidate endpoints for level/XP data...", file=sys.stderr)
    for template in LEVEL_ENDPOINT_CANDIDATES:
        path = template.format(id=user_id)
        try:
            resp = session.get(f"{API_BASE}{path}", timeout=15)
        except requests.RequestException as e:
            print(f"[debug] probe {path}: error ({e})", file=sys.stderr)
            continue

        print(f"[debug] probe {path}: {resp.status_code}", file=sys.stderr)
        if resp.status_code != 200:
            continue
        try:
            data = resp.json()
        except ValueError:
            continue

        debug_save(f"probe:{path}", data)
        if isinstance(data, dict):
            print(f"[debug]   keys: {sorted(data.keys())}", file=sys.stderr)
        level_like = {
            k: v for d in _iter_dicts(data) for k, v in d.items()
            if "level" in k.lower() or "xp" in k.lower()
        }
        if level_like:
            print(f"[debug]   possible level/XP fields: {level_like}", file=sys.stderr)


def get_repo_info():
    """Best-effort: resolve the current git remote + branch so we can print
    a ready-to-use raw.githubusercontent.com embed URL. Returns None if this
    isn't a GitHub git repo (e.g. run outside a clone)."""
    try:
        remote = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        match = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?$", remote)
        if match and branch and branch != "HEAD":
            return match.group(1), match.group(2), branch
    except (subprocess.SubprocessError, OSError):
        pass
    return None


def get_token():
    token = os.environ.get("HTB_APP_TOKEN")
    if token:
        return token
    token = getpass.getpass("HTB_APP_TOKEN is not set. Paste your HTB App Token (input hidden): ").strip()
    if not token:
        raise SystemExit(
            "No token provided. Create a free App Token at app.hackthebox.com "
            "(account settings -> App Tokens), then either set it as an "
            "environment variable (export HTB_APP_TOKEN=...) or paste it when prompted."
        )
    return token


def main():
    global DEBUG

    parser = argparse.ArgumentParser(description="Generate an HTB profile badge (SVG).")
    parser.add_argument("target", help="HTB username or profile URL (e.g. https://app.hackthebox.com/profile/123456)")
    parser.add_argument("-o", "--output", default="assets/htb_badge.svg", help="Output SVG path")
    parser.add_argument(
        "--debug", action="store_true",
        help=f"Dump raw API responses to {DEBUG_FILE} and print the profile's field names, "
             "useful for spotting HTB field names this script doesn't know about yet.",
    )
    args = parser.parse_args()
    DEBUG = args.debug

    token = get_token()

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "htb-badge-generator (github.com/b0neng/htbbadge)",
    })

    user_id = resolve_target(session, args.target)
    profile = fetch_profile(session, user_id)
    avatar_data_uri = fetch_avatar_data_uri(profile["avatar"])
    svg = build_svg(profile, avatar_data_uri)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(svg)

    profile_url = f"https://app.hackthebox.com/profile/{user_id}"
    print(f"Badge written to {args.output} for user '{profile['name']}' (id={user_id}).")
    print(f"Profile: {profile_url}")
    if DEBUG:
        probe_level_endpoints(session, user_id)
        print(f"\nRaw API responses saved to {DEBUG_FILE}")

    repo_info = get_repo_info()
    print("\nEmbed in a GitHub README:")
    if repo_info:
        owner, repo, branch = repo_info
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{args.output}"
        print(f"[![HTB Badge]({raw_url})]({profile_url})")
    else:
        print(f"[![HTB Badge]({args.output})]({profile_url})")


if __name__ == "__main__":
    main()
