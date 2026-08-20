# HTBbadge

_Made by fer_

I wanted a GitHub badge for my [Hack The Box](https://www.hackthebox.com/) profile, the same way TryHackMe has one - but HTB doesn't offer one anymore. So I built this: a small script that pulls your real stats from HTB and generates a clean SVG card, same size and style as the official TryHackMe badge.

![example badge](assets/example.svg)

_(placeholder data above - run the script to generate your own)_

## Setup

1. Grab a free **App Token**: log in at [app.hackthebox.com](https://app.hackthebox.com) -> account settings -> **App Tokens**. No subscription needed.
2. Set up a virtual environment and install the one dependency (required on Kali/Debian):
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

## Usage

```bash
python htb_badge.py https://app.hackthebox.com/public/users/123456
```

Use your **profile URL** (username lookup has a known bug - see below). If `HTB_APP_TOKEN` isn't set, the script asks for it (hidden input). To skip that prompt:

```bash
export HTB_APP_TOKEN=your_token_here
```

This writes `assets/htb_badge.svg`. Commit and push it to actually see it on GitHub - generating the file alone does nothing:

```bash
git add assets/htb_badge.svg
git commit -m "Update HTB badge"
git push
```

The script prints a ready-to-paste embed snippet after every run, with your profile link filled in. Drop it straight into a README:

```markdown
[![HTB Badge](assets/htb_badge.svg)](https://app.hackthebox.com/public/users/123456)
```

Pasting into a different repo (like your GitHub profile README)? The script detects that and gives you a full `raw.githubusercontent.com` link instead of a relative path.

## Updating

No auto-update - re-run the script and push whenever you want fresh numbers:

```bash
python htb_badge.py https://app.hackthebox.com/public/users/123456
git add assets/htb_badge.svg && git commit -m "Update HTB badge" && git push
```

## Known issue

Looking up by username (`python htb_badge.py fer`) currently fails - HTB's search endpoint rejects the request format. **Use your profile URL instead**, it's confirmed working and doesn't touch that endpoint at all.

## Notes

- Something look wrong or show `N/A`? Run with `--debug` - it prints the raw field names/values HTB actually returned (skipping personal info like your name/phone/timezone) so a mismatch can be spotted and fixed.
- "Pwned" counts machines where you have both flags, matching your HTB profile's own "Machines" count.
- Streak counts full weeks (200+ XP), not the current in-progress one - same rule HTB itself uses.
- Card is a fixed 329x88px to match TryHackMe's badge exactly. Very long names get truncated rather than stretching the card.
- Built on HTB's undocumented APIs (reverse-engineered via browser DevTools), not an official integration - it may need small fixes if HTB changes something.

## License

[MIT](LICENSE) - use it, fork it, change it.
