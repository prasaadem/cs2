# CS2 Nights

Stats site for our CS2 server, built from the DatHost server logs.

## How it works

Every day at 9 AM Pacific a GitHub Action ([daily-stats.yml](.github/workflows/daily-stats.yml)) does the following:

1. Downloads the server's `logs/` folder from the DatHost API (`stats/fetch_dathost.py`).
2. Parses the logs and merges any new games into `data/games/` (`stats/update_stats.py`).
3. Rebuilds the site in `docs/` (`stats/build_site.py`).
4. Commits and pushes, recording the sync time shown on the page.
5. If there were new games, posts a summary to Discord (`stats/notify_discord.py`).

GitHub Pages serves `docs/`.

## The archive: `data/games/`

There is one JSON file per game, named `<UTC start YYYYMMDD-HHMM>-<map>.json`. This folder is the permanent record. DatHost only keeps about a month of logs, so the archive holds games the server no longer has. The merge rules protect it:

- New games are added.
- A completed game is never changed.
- An unfinished game is replaced only by a version with more rounds, for example when a log was still being written during the last download.
- Nothing is ever deleted.

Raw logs are never committed, because they contain passwords and player IP addresses.

## Setup

- **Repository secrets** (Settings → Secrets and variables → Actions):
  - `DATHOST_EMAIL` and `DATHOST_PASSWORD`: a DatHost login. Ideally use a separate login invited to the server's account.
  - `DATHOST_SERVER_ID`: the ID from the control panel URL, `dathost.net/control-panel/game-servers/<id>`.
  - `DATHOST_ACCOUNT_EMAIL` (optional): the account owner's email, if the login above was invited to that account.
  - `DISCORD_WEBHOOK_URL` (optional): a channel webhook (Edit Channel → Integrations → Webhooks). When a sync brings new games, the job posts a summary for each night after the site has updated. Nothing is posted on days without new data.
- **Pages:** Settings → Pages → Deploy from branch `main`, folder `/docs`.
- **Manual run:** Actions → Daily stats → Run workflow.

## Running locally

```bash
python stats/update_stats.py --logs path/to/logs   # add games from a folder of .log files
python stats/build_site.py                         # rebuild docs/
python -m http.server 8765 --directory docs        # view at http://localhost:8765
```

The page loads `data/games.json`, so it must be served over HTTP. Opening the file directly won't load the data.

## Stats notes

- **Rating** is an HLTV 1.0-style rating, where 1.00 is average.
- **MVP** is the best rating in a game, among players who played at least half the rounds.
- **W–L** counts completed games only.
- **ADR** comes from the server's round summaries and excludes each game's last round.
- Every game records `v` (the parser version). Metrics added later appear for new games only. Older games show "–" for them.
