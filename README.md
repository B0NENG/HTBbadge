# HTBbadge

_Made by fer_

A [Hack The Box](https://www.hackthebox.com/) profile badge generator for your GitHub README, styled like the official TryHackMe badge: avatar, rank, points, boxes pwned, global ranking and level - as a clean SVG card in HTB's green/black look.

HTB doesn't offer an official stats badge anymore (the old `hackthebox.eu/badge/...` signature system is defunct), so this script builds one from the real HTB API instead.

![example badge](assets/example.svg)

_(example above uses placeholder data - run the script to generate your own)_

## Setup

1. Create a free **App Token**: log in at [app.hackthebox.com](https://app.hackthebox.com), go to your account settings -> **App Tokens**, and generate one. No subscription needed - HTB's API requires this token even to read someone's public profile.
2. Create a virtual environment and install dependencies. This is required on Debian/Kali-based systems (`pip install` alone fails there with `externally-managed-environment`):
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
   You'll need to run `source venv/bin/activate` again in any new terminal before using the script.
3. Provide your token when you run the script (see [Usage](#usage) below) - either as an environment variable, or by pasting it when prompted.

## Usage

Run with your full profile URL (recommended - see the known issue below) or your HTB username:

```bash
python htb_badge.py https://app.hackthebox.com/profile/123456
# or
python htb_badge.py fer
```

If `HTB_APP_TOKEN` isn't set in your environment, the script will prompt you to paste it (input is hidden, and it's never written to shell history). To skip the prompt instead:

```bash
export HTB_APP_TOKEN=your_token_here
python htb_badge.py fer
```

This writes the badge to **`assets/htb_badge.svg`**, relative to wherever you run the command from. Generating the file locally doesn't do anything by itself - to actually see it on GitHub or use it in a profile README, you need to commit and push it:

```bash
git add assets/htb_badge.svg
git commit -m "Update HTB badge"
git push
```

After every run, the script also prints a ready-to-paste embed snippet with your profile link already filled in - copy that straight into a README. Wrapping the image in a markdown link (`[![...](...)](...)`, exactly what the printed snippet does) is what makes it clickable on GitHub, the same way the TryHackMe badge links back to a THM profile - the image itself isn't clickable on its own, this wrapper is what makes it work.

If you're pasting the snippet into a **different repo** (e.g. your GitHub profile README, which lives in a repo named `<your-username>/<your-username>`), the script detects that and gives you a `raw.githubusercontent.com` link that works from anywhere, instead of a relative path that would only work inside this repo.

### Debugging incorrect stats

If a stat looks wrong (or shows `N/A`), HTB likely uses a different field name than this script expects - re-run with `--debug`:

```bash
python htb_badge.py fer --debug
```

This prints every field name found in your profile response, the values of the fields this script actually uses (name, rank, points, owns, ranking - deliberately excluding personal fields like your full name, phone number, or timezone that HTB's response also includes), and saves the full raw API response to `debug_response.json` (gitignored, never committed). Share the printed values (not necessarily the full file) if you need a field mapping fixed.

## Updating the badge

There's no auto-update in this version. When you've pwned more boxes, just re-run the script and commit the new `assets/htb_badge.svg`:

```bash
python htb_badge.py fer
git add assets/htb_badge.svg
git commit -m "Update HTB badge"
git push
```

## Known issue

Username lookup (`python htb_badge.py fer`) currently fails with a `422` error from HTB's search endpoint - the exact parameters it expects haven't been confirmed yet. **Use your full profile URL instead** (`python htb_badge.py https://app.hackthebox.com/profile/<id>`), which doesn't depend on that endpoint at all and is confirmed working. Run with `--debug` if you want to help pin down the search endpoint's expected format - it now prints the response body on API errors.

## Notes

- The avatar is downloaded and embedded directly into the SVG (not hotlinked) using a separate, unauthenticated request - so the badge renders correctly on GitHub, and HTB's own API token is never sent to the third-party host serving the image. If the download fails for any reason, a placeholder icon is shown instead of a broken image.
- "Pwned" counts machines where you have **both** flags (`min(user_owns, system_owns)`), matching the "Machines" counter on your HTB profile - not the sum of user + root flags separately.
- HTB doesn't have a "streak" stat the way TryHackMe does (confirmed via `--debug` against a real profile).
- The **rank tag** shown next to your name comes straight from HTB's `rank` field, which may lag behind the newer level/tier system shown on your profile page (e.g. it can say "Noob" when your profile shows "Apprentice"). The **Level** stat has the same caveat - HTB's API doesn't expose an obvious `level` field yet, so it may show `N/A` until the right field is identified (run with `--debug` and check the `possible level/XP fields` line, or share the printed field values so this can be fixed precisely).
- This uses HTB's undocumented v4 API (reverse-engineered by the community, see [Gubarz/unofficial-htb-api](https://github.com/Gubarz/unofficial-htb-api)), not an officially supported integration. If HTB changes their response format, the script prints a warning about which fields it couldn't find rather than failing silently.
