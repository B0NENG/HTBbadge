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
EXPERIENCE_API_BASE = "https://labs.hackthebox.com/api/experience/v1"
SITE_BASE = "https://www.hackthebox.com"
ROMAN_GRADE = {"1": "I", "2": "II", "3": "III"}
PROFILE_URL_RE = re.compile(r"hackthebox\.(?:com|eu)/(?:profile|public/users|users)/(\d+)")
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
            "e.g. https://app.hackthebox.com/public/users/123456"
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
        key for key in ("name", "user_owns", "system_owns")
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
        "ranking": pick(profile, "ranking", "rank_position", default=None),
        "user_owns": int(pick(profile, "user_owns", "userOwns", default=0) or 0),
        "system_owns": int(pick(profile, "system_owns", "systemOwns", default=0) or 0),
        "account_id": pick(profile, "account_id", default=None),
        "avatar": normalize_avatar(pick(profile, "avatar", "avatar_thumb")),
    }


def fetch_experience(session, account_id):
    """Level/XP/streak data lives on a completely separate API
    ("experience", not /api/v4/...) keyed by the account's UUID rather
    than its numeric user id. That UUID comes from the `account_id`
    field already present in the basic profile response.

    This is what actually reflects HTB's current Level/Tier system
    (e.g. "Apprentice I", Lvl 19) - the `rank`/`rank_id` fields from
    /user/profile/basic belong to HTB's older, separate Noob/Script
    Kiddie/.../Omniscient ranking and can be stale/misleading by
    comparison."""
    if not account_id:
        return None
    try:
        resp = session.get(f"{EXPERIENCE_API_BASE}/account/{account_id}", timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"Warning: could not fetch level/XP data ({e}).", file=sys.stderr)
        return None

    if DEBUG:
        debug_save("experience_account", data)
        print(f"[debug] experience keys: {sorted(data.keys())}", file=sys.stderr)

    streak = data.get("streakData") or {}
    return {
        "level": data.get("level"),
        "level_title": data.get("levelTitle"),
        "level_grade": data.get("levelGrade"),
        "total_xp": data.get("totalExperiencePoints"),
        "streak_weeks": streak.get("counter"),
    }


# Minimal line-icon paths (Feather-icon style, 24x24 viewBox).
ICON_FLAG = '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/>'
ICON_TREND = '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>'
ICON_LEVEL = '<circle cx="12" cy="8" r="7"/><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"/>'
ICON_FLAME = '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>'

# Sampled directly from the user's real TryHackMe badge PNG (pixel analysis
# via Pillow, not a guess) so the stat icons use the same accent colors as
# their THM badge - trophy/silver, streak/green, badge/magenta, follower/blue.
ICON_COLOR_LEVEL = "#9CA4B4"
ICON_COLOR_PWNED = "#A3EA2A"
ICON_COLOR_RANK = "#D752FF"
ICON_COLOR_STREAK = "#719CF9"

FONT_STACK = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

AVATAR_FALLBACK = (
    '<rect x="5" y="17" width="54" height="54" fill="#2d3746" clip-path="url(#avatarClip)"/>'
    '<circle cx="32" cy="32" r="11" fill="#6e7f96" clip-path="url(#avatarClip)"/>'
    '<circle cx="32" cy="66" r="20" fill="#6e7f96" clip-path="url(#avatarClip)"/>'
)

# Fixed to match the TryHackMe badge's own dimensions exactly (329x88px PNG,
# fetched and measured directly), per the user's request for equal sizing.
CARD_WIDTH = 329
CARD_HEIGHT = 88
CONTENT_X = 74


def icon(path_data, x, y, size=16, color="#9FEF00", filled=False):
    scale = size / 24
    style = f'fill="{color}" stroke="none"' if filled else (
        f'fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'
    )
    return (
        f'<g transform="translate({x},{y}) scale({scale})">'
        f'<g {style}>'
        f'{path_data}</g></g>'
    )


def truncate(text, max_chars):
    """Fixed-size card = fixed space, unlike the old auto-growing width -
    long names/values must be clipped rather than pushing the card wider."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def stat_column(x, icon_svg, value):
    return f"""
    <g>
      {icon_svg}
      <text x="{x + 16}" y="{57}" font-family="{FONT_STACK}" font-size="12" font-weight="600" fill="#e6edf3">{escape(str(value))}</text>
    </g>"""


def build_svg(data, experience=None, avatar_data_uri=None):
    experience = experience or {}
    name = escape(truncate(str(data["name"]), 14))

    # Prefer HTB's current Level/Tier system (e.g. "Apprentice I") over the
    # older rank field (e.g. "Noob") from /user/profile/basic - the two are
    # separate systems and the older one can look stale/wrong by comparison.
    level_title = experience.get("level_title")
    if level_title:
        grade = ROMAN_GRADE.get(str(experience.get("level_grade")), "")
        rank = f"{level_title} {grade}".strip()
    else:
        rank = str(data["rank"])
    rank = escape(truncate(rank, 14))

    # A machine only counts as "pwned" once both flags are captured, so
    # this is min() rather than a sum of the two flag counts (confirmed
    # against a real profile: user_owns=5, system_owns=4 -> 4 machines
    # fully owned, matching HTB's own "Machines" counter).
    boxes_pwned = min(data["user_owns"], data["system_owns"])
    ranking = data["ranking"]
    ranking_display = f"#{ranking:,}" if isinstance(ranking, int) else "N/A"

    level = experience.get("level")
    level_display = str(level) if isinstance(level, (int, float)) else "N/A"

    streak_weeks = experience.get("streak_weeks")
    streak_display = str(streak_weeks) if isinstance(streak_weeks, (int, float)) else "N/A"

    # No per-stat labels (POINTS/PWNED/...) - there's no room for them at
    # this fixed height, so this leans on icon+number pairs only, the same
    # way TryHackMe's own badge communicates its stats. Icon colors are
    # sampled from that same THM badge (see ICON_COLOR_* above).
    columns = [
        (ICON_LEVEL, truncate(level_display, 8), ICON_COLOR_LEVEL, False),
        (ICON_FLAG, truncate(str(boxes_pwned), 8), ICON_COLOR_PWNED, False),
        (ICON_TREND, truncate(ranking_display, 8), ICON_COLOR_RANK, False),
        (ICON_FLAME, truncate(streak_display, 8), ICON_COLOR_STREAK, True),
    ]
    stats_parts = []
    x = CONTENT_X
    for icon_path, value, color, filled in columns:
        stats_parts.append(stat_column(x, icon(icon_path, x, 45, size=13, color=color, filled=filled), value))
        x += max(len(value) * 7, 10) + 25
    stats = "".join(stats_parts)

    avatar_svg = (
        f'<image href="{escape(avatar_data_uri)}" x="5" y="17" width="54" height="54" '
        f'clip-path="url(#avatarClip)" preserveAspectRatio="xMidYMid slice"/>'
        if avatar_data_uri else AVATAR_FALLBACK
    )

    return f"""<svg width="{CARD_WIDTH}" height="{CARD_HEIGHT}" viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" role="img" aria-label="Hack The Box profile badge for {name}">
  <title>Hack The Box profile badge for {name}</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0d1117"/>
      <stop offset="100%" stop-color="#141d2b"/>
    </linearGradient>
    <pattern id="hex" width="16" height="14" patternUnits="userSpaceOnUse" patternTransform="translate(0,0)">
      <path d="M8 0 L16 4.7 L16 9.3 L8 14 L0 9.3 L0 4.7 Z" fill="none" stroke="#9FEF00" stroke-opacity="0.06" stroke-width="1"/>
    </pattern>
    <clipPath id="avatarClip">
      <circle cx="32" cy="44" r="27"/>
    </clipPath>
  </defs>

  <rect x="0.75" y="0.75" width="{CARD_WIDTH - 1.5}" height="{CARD_HEIGHT - 1.5}" rx="8" fill="url(#bg)" stroke="#9FEF00" stroke-opacity="0.55" stroke-width="1.5"/>
  <rect x="0.75" y="0.75" width="{CARD_WIDTH - 1.5}" height="{CARD_HEIGHT - 1.5}" rx="8" fill="url(#hex)"/>

  <circle cx="32" cy="44" r="28" fill="none" stroke="#9FEF00" stroke-width="1.5"/>
  {avatar_svg}

  <text x="{CONTENT_X}" y="23" font-family="{FONT_STACK}" font-size="13" font-weight="700" fill="#e6edf3">{name}</text>
  <g transform="translate({CONTENT_X + len(name) * 7.2 + 8},13)">
    <rect width="{len(rank) * 5.2 + 12}" height="14" rx="7" fill="#9FEF00" fill-opacity="0.12" stroke="#9FEF00" stroke-opacity="0.5"/>
    <text x="6" y="10.5" font-family="{FONT_STACK}" font-size="8" font-weight="600" fill="#9FEF00">{rank}</text>
  </g>

  <line x1="{CONTENT_X}" y1="32" x2="{CARD_WIDTH - 12}" y2="32" stroke="#9FEF00" stroke-opacity="0.2" stroke-width="1"/>

  {stats}

  <text x="{CONTENT_X}" y="{CARD_HEIGHT - 8}" font-family="{FONT_STACK}" font-size="7" fill="#7d8590">hackthebox.com</text>
  <text x="{CARD_WIDTH - 10}" y="{CARD_HEIGHT - 8}" text-anchor="end" font-family="{FONT_STACK}" font-size="8" font-weight="700" fill="#9FEF00">{escape(CREDIT)}</text>
</svg>
"""


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
    parser.add_argument("target", help="HTB username or profile URL (e.g. https://app.hackthebox.com/public/users/123456)")
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
    experience = fetch_experience(session, profile["account_id"])
    avatar_data_uri = fetch_avatar_data_uri(profile["avatar"])
    svg = build_svg(profile, experience, avatar_data_uri)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(svg)

    profile_url = f"https://app.hackthebox.com/public/users/{user_id}"
    print(f"Badge written to {args.output} for user '{profile['name']}' (id={user_id}).")
    print(f"Profile: {profile_url}")
    if DEBUG:
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
