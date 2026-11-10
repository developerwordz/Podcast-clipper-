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


## Resuming / refreshing existing sources

If a feed times out, it is skipped and the run continues. To retry all saved feeds
without repeating podcast-directory searches:

```powershell
python main.py --refresh-saved
```

Each feed has a bounded network timeout. Any episode records saved before an
interruption remain in SQLite.
## Milestone 2 - Episode Intelligence

ClipPulse can now evaluate discovered podcast episodes using
a heuristic relevance scoring system.

### Rank episodes

python main.py --rank-episodes

### Display more candidates

python main.py --rank-episodes --top 50

### Filter by minimum score

python main.py --rank-episodes --min-score 70

### Ranking tiers

- HIGH: 70-100
- MEDIUM: 50-69
- LOW: 0-49

Episode scores are saved in SQLite and are not recalculated
unless the ranking fields are reset.

Scores estimate content relevance, not viral potential.
Permission to republish must be verified separately.