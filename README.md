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

## Join/leave timeline: `data/presence/`

`stats/presence.py` reads the connect, entered-the-game and disconnect lines from the same logs and saves each night's stays as `data/presence/<night>.json` (player id, name, join and leave time in UTC, leave reason). The IP address on the connect line is never stored. A map change drops everyone for a moment, so stays less than two minutes apart are joined into one. The same never-delete rule as the games applies: stays are only added or extended, so nights whose logs DatHost has dropped stay intact. Nights from before this existed have no data and keep the games-based table. The Attendance page for a night draws the timeline from `docs/data/presence.json`.

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

The Server page calls a Cloudflare Worker; DatHost credentials are never placed in the static site. The Worker provides status and power controls, a map selector from the server's approved map list, and fixed console presets for `mp_forcecamera 1`, `mp_warmup_end 1`, and `mp_restartgame 1`. Console commands and map names are allow-listed in the Worker; arbitrary browser-supplied commands are rejected. Server stop/restart, match restart, warmup end, and map changes require confirmation in the page.

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

### Live presence ("Now playing")

A Worker cron trigger (`[triggers]` in `worker/wrangler.toml`, every minute) checks DatHost and keeps a small snapshot in the `RATINGS` KV namespace under the key `live:presence`: whether the server is on, the map, and the connected players' names. No IDs or addresses are stored. The snapshot is written when it changes and otherwise every 10 minutes, which keeps KV writes well under the free limit.

`GET /api/presence` serves that snapshot to the allowed site origins with no sign-in, limited to 30 requests a minute per IP, and never calls DatHost itself. If the snapshot is more than 15 minutes old (the checker stopped) it answers `{"available": false}`. The Server page shows it as "Now playing" above the controls and refreshes every 30 seconds.

No new secrets are needed. Deploying the Worker (`npx wrangler deploy --config worker/wrangler.toml`) registers the cron trigger.

### Team balancer

The daily job computes player ratings (`stats/ratings.py`) and sends them to the Worker, which keeps them in KV. The ratings never go into `docs/` or `data/`, and no endpoint returns them.

- `PUT /ratings`: used only by the daily job. It needs `Authorization: Bearer <RATINGS_TOKEN>`.
- `POST /api/split` with `{"players": ["name", "[U:1:123]", ...]}` (2 to 16 players): returns two rosters (one random captain per team, listed first and marked `captain: true`) and a balance label (`even`, `close` or `uneven`). Players are matched by name or Steam ID. Unknown players count as the group average and are listed in `unknown`. This endpoint is open to the allowed site origins and limited to 20 requests a minute per IP.

Each player's strength is their overall **Rating** from the site leaderboard: the HLTV 1.0-style rating from their kill, death, survival and multi-kill totals across every game. The split keeps the two teams' average ratings as close as possible. When the lobby is odd, the short team gets an average rating about 0.1 higher, because a team down a player won about 45% of rounds in the archive. Players not in the stats count as the group average.

One-time setup:

```bash
npx wrangler kv namespace create RATINGS --config worker/wrangler.toml   # already done; the id is in wrangler.toml
# one token, sent to both Cloudflare and GitHub without ever being printed
t=$(openssl rand -hex 32); printf %s "$t" | npx wrangler secret put RATINGS_TOKEN --config worker/wrangler.toml; printf %s "$t" | gh secret set RATINGS_TOKEN; unset t
npx wrangler deploy --config worker/wrangler.toml
```

Then set the GitHub secret `RATINGS_PUBLISH_URL` to the Worker URL followed by `/ratings`. To rotate the token, run the `t=...` line again.

### Discord `/teams`

In Discord, typing `/teams` shows you a private dropdown of the 25 most recent players. Tick who's playing and close it, and the bot posts two balanced teams to the channel, each with a randomly chosen captain shown first in bold. To include a guest who isn't in the list, use `/teams players: Sheldor, Rat, Guest, ...` with in-game names or Steam IDs separated by commas. Players with fewer than 5 games are marked "(new)". Ratings are never shown. Discord sends each command to `POST /discord/interactions`, and the Worker checks Discord's signature with `DISCORD_PUBLIC_KEY` (set in `wrangler.toml`).

Setup (once):

1. Deploy the Worker.
2. In the Discord Developer Portal, under General Information, set the **Interactions Endpoint URL** to `<worker url>/discord/interactions` and save. Discord tests the URL before it accepts it.
3. Register the command in your server. Run this with the bot token on your clipboard. The token isn't stored anywhere.

   ```bash
   DISCORD_BOT_TOKEN=$(pbpaste) node worker/scripts/register-discord-command.mjs
   ```

### Discord `/server`

Only members with **Manage Server** or **Administrator** can use these commands. Discord hides them from everyone else, and the Worker checks the permission again on every request. Each command sends one fixed, allow-listed action to DatHost, the same ones the Server page uses:

- `/server start`: start the game server. When it starts successfully, the bot also posts **last night's grudges**. This covers only the most recent game night, skips `aim_`/`awp_` warm-up maps, and lists each player's nemesis, the biggest rivalries, and duos who won or lost every game together (3+ games). The daily job builds the message with `stats/recap.py` and sends it with the ratings. Run `python stats/recap.py` to preview it.
- `/server stop`: stop the game server. It first asks privately for confirmation with a **Stop server** button.
- `/server restart-game`: restart the match with `mp_restartgame 1`, which resets scores to 0-0. It first asks privately for confirmation with a **Restart match** button.
- `/server map name:<map>`: change the map. Start typing a name and matching maps are suggested. Only maps from the approved list are accepted.
- `/server warmup-end`: run `mp_warmup_end 1`
- `/server forcecamera`: run `mp_forcecamera 1`

The bot replies publicly, shows "thinking…" while DatHost responds, then edits the reply to show the result and who ran it. After changing these commands, run the registration script again (the `/teams` setup steps above have the command).

Run the Worker unit tests locally with `node --test worker/test/worker.test.mjs`.

## Stats notes

- **Rating** is an HLTV 1.0-style rating, where 1.00 is average.
- **MVP** is the best rating in a game, among players who played at least half the rounds.
- **W–L** counts completed games only.
- **ADR** comes from the server's round summaries and excludes each game's last round.
- Every game records `v` (the parser version). Metrics added later appear for new games only. Older games show "–" for them.
