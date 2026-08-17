# HTBbadge

_Made by fer_

A [Hack The Box](https://www.hackthebox.com/) profile badge generator for your GitHub README, styled like the official TryHackMe badge: avatar, rank, points, boxes pwned, global ranking and respect - as a clean SVG card in HTB's green/black look.

HTB doesn't offer an official stats badge anymore (the old `hackthebox.eu/badge/...` signature system is defunct), so this script builds one from the real HTB API instead.

![example badge](assets/example.svg)

_(example above uses placeholder data - run the script to generate your own)_

## Setup

1. Create a free **App Token**: log in at [app.hackthebox.com](https://app.hackthebox.com), go to your account settings -> **App Tokens**, and generate one. No subscription needed - HTB's API requires this token even to read someone's public profile.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set the token as an environment variable:
   ```bash
   export HTB_APP_TOKEN=your_token_here
   ```

## Usage

Run with either your HTB username or your full profile URL:

```bash
python htb_badge.py fer
# or
python htb_badge.py https://app.hackthebox.com/profile/123456
```

This writes `assets/htb_badge.svg`. Commit and push it, then embed it in your GitHub profile README, linked to your HTB profile (the same pattern the TryHackMe badge uses):

```markdown
[![HTB Badge](assets/htb_badge.svg)](https://app.hackthebox.com/profile/123456)
```

## Updating the badge

There's no auto-update in this version. When you've pwned more boxes, just re-run the script and commit the new `assets/htb_badge.svg`:

```bash
python htb_badge.py fer
git add assets/htb_badge.svg
git commit -m "Update HTB badge"
git push
```

## Notes

- The username lookup uses HTB's search API and falls back with a clear error if it can't resolve a name - if that happens, pass your full profile URL instead (most reliable, no lookup needed).
- This uses HTB's undocumented v4 API (reverse-engineered by the community, see [Gubarz/unofficial-htb-api](https://github.com/Gubarz/unofficial-htb-api)), not an officially supported integration. If HTB changes their response format, the script will print a warning about which fields it couldn't find rather than failing silently.
