# CS2 Nights

Stats site for our CS2 server, built from the DatHost server logs.

## How it works

Every day at 9 AM Pacific a GitHub Action ([daily-stats.yml](.github/workflows/daily-stats.yml)) does the following:

1. Downloads the server's `logs/` folder and any new GOTV demos from the DatHost API (`stats/fetch_dathost.py`).
2. Parses the logs and merges any new games into `data/games/` (`stats/update_stats.py`).
3. Converts new demos into replay files in `docs/data/replays/` (`stats/demo_replays.py`, needs `pip install demoparser2`). These are kept forever, like the stats.
4. Rebuilds the site in `docs/` (`stats/build_site.py`).
5. Commits and pushes, recording the sync time shown on the page.
6. If there were new games, posts a summary to Discord (`stats/notify_discord.py`).

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

## Replays (GOTV demos)

The server records every map with `tv_autorecord 1` (in `cfg/server.cfg`); DatHost keeps the demos in `replays/` for 14 days. Each match becomes `docs/data/replays/<game id>.json`: every player's position and facing twice a second, plus rounds, kills, smokes and fires. The Replays page plays them back on the map radar. Raw demos are never committed.

## Map radars

`python stats/extract_radars.py` copies radar images and overview files for every played map from a local CS2 install into `docs/radar/` (see `docs/radar/README.md`).

## Running locally

Put `DATHOST_EMAIL`, `DATHOST_PASSWORD` and `DATHOST_SERVER_ID` (and `DATHOST_ACCOUNT_EMAIL` if needed) in a `.env` file in the repo root. It is never committed.

```bash
python stats/fetch_dathost.py --out ../logs --demos ../demos   # download logs and demos
python stats/demo_replays.py --demos ../demos                    # demos -> replays
```

```bash
python stats/update_stats.py --logs path/to/logs   # add games from a folder of .log files
python stats/build_site.py                         # rebuild docs/
python -m http.server 8765 --directory docs        # view at http://localhost:8765
```

The page loads `data/games.json`, so it must be served over HTTP. Opening the file directly won't load the data.

## Server controls

The Server page calls a Cloudflare Worker; DatHost credentials are never placed in the static site. The Worker provides status, start, stop, restart, and a fixed `mp_warmup_end` console action behind a passphrase and short-lived signed sessions. Stop, restart, and ending warmup require confirmation in the page.

Deploy the Worker from the repository root with Wrangler (Node.js required):

```bash
npx wrangler login
npx wrangler deploy --config worker/wrangler.toml
```

Add these Worker secrets. Wrangler prompts for each value; use the DatHost values from your local `.env` without pasting them into source files or chat:

```bash
npx wrangler secret put DATHOST_EMAIL --config worker/wrangler.toml
npx wrangler secret put DATHOST_PASSWORD --config worker/wrangler.toml
npx wrangler secret put DATHOST_SERVER_ID --config worker/wrangler.toml
npx wrangler secret put DATHOST_ACCOUNT_EMAIL --config worker/wrangler.toml  # optional
npx wrangler secret put CONTROL_PASSPHRASE --config worker/wrangler.toml
openssl rand -hex 32 | npx wrangler secret put SESSION_SECRET --config worker/wrangler.toml
npx wrangler deploy --config worker/wrangler.toml
```

Use a unique, randomly generated control passphrase of at least 32 characters and save it in a password manager. The random session-signing key is generated locally and piped directly to Wrangler. The free Workers plan has usage limits; check Cloudflare's current limits for your account before deploying.

The allowed site origins are configured in `worker/wrangler.toml` for `https://prasaadem.github.io` and local preview on port 8765. If the Pages domain changes, update `ALLOWED_ORIGINS` and redeploy. After deployment, open `#/server` on the site, enter the Worker URL shown by Wrangler and the control passphrase, then unlock. The passphrase is sent only to the Worker over HTTPS; the returned token expires after 15 minutes and is kept in browser local storage so the session survives reloads until expiry or sign-out.

Run the Worker unit tests locally with `node --test worker/test/worker.test.mjs`.

## Stats notes

- **Rating** is an HLTV 1.0-style rating, where 1.00 is average.
- **MVP** is the best rating in a game, among players who played at least half the rounds.
- **W–L** counts completed games only.
- **ADR** comes from the server's round summaries and excludes each game's last round.
- Every game records `v` (the parser version). Metrics added later appear for new games only. Older games show "–" for them.
