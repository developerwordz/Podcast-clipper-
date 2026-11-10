# ClipPulse — Milestone 1: Podcast Discovery

ClipPulse is a Python project for discovering podcast sources and indexing public RSS episode metadata.

## What this milestone does

- Searches the Apple Podcasts directory using its public Search API.
- Finds podcast RSS feed URLs.
- Reads episode titles, descriptions, dates, durations and audio enclosure URLs.
- Stores source and episode metadata in a local SQLite database.
- Keeps every source marked `UNREVIEWED` until you confirm you have permission to republish its content.

## What it deliberately does NOT do yet

- It does not download podcast audio or video.
- It does not bypass paywalls, DRM, login restrictions or platform protections.
- It does not assume that a public RSS feed grants republication rights.
- It does not upload anything to YouTube or Instagram.

## Windows setup

Open PowerShell in the extracted `ClipPulse` folder:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

If PowerShell blocks activation, run this for the current terminal only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Search specific topics

```powershell
python main.py --search "Indian business podcast" --search "AI technology podcast" --limit 15
```

## List saved sources

```powershell
python main.py --list-sources
```

## Permission tracking

Only after obtaining explicit permission or confirming a licence that permits the intended reuse:

```powershell
python main.py --approve-source 1 --permission-note "Creator granted written permission on 2026-11-10"
```

Approval is a local workflow flag, not a legal verification. Keep the actual permission evidence separately.

## Database

SQLite database: `database/clippulse.db`

The next milestone will add a reviewable episode shortlist and a transcript-based moment detector.
