# PydanticAI Telegram Bot

Simple Telegram bot built with PydanticAI, an OpenAI-compatible provider, and a small plugin contract that is easy to extend later.

## Features

- Telegram long polling
- Local web chat UI via `Agent.to_web()`
- Explicit plugin loading
- Per-plugin CLI entrypoints for isolated testing
- Example `get_time` tool plugin
- Optional `intervals_icu` plugin for wellness, weekly load progress, and activities
- Optional `open_meteo` plugin for geocoding and weather forecasts
- Optional `route_planner` plugin for GPX route generation via BRouter

## Setup

1. Copy `.env.example` to `.env` or export the variables in your shell.
2. Install dependencies:

```bash
make install
```

3. Set these variables:

- `OPENAI_MODEL`
- `OPENAI_BASE_URL` if you want to target an OpenAI-compatible provider instead of OpenAI directly
- `OPENAI_API_KEY` if your provider requires one
- `TELEGRAM_BOT_TOKEN` for Telegram mode
- `TELEGRAM_AUTHORIZED_USERS` as a comma-separated list of allowed Telegram usernames or numeric user IDs
- `APP_PUBLIC_BASE_URL` if you want absolute clickable download links in web or Telegram replies
- `INTERVALS_ICU_API_KEY` and `INTERVALS_ICU_ATHLETE_ID` if you enable the Intervals.icu plugin
- `ROUTE_PLANNER_BROUTER_URL` if you enable the route planner plugin
- `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` if you want route planner to avoid known roads using Strava history

## Run

Start Telegram bot:

```bash
make telegram
```

Start local web UI:

```bash
make web
```

Start Telegram bot and local web UI together:

```bash
make run-both
```

Run the example tool directly:

```bash
make tool-get-time
```

Example with timezone:

```bash
uv run get-time-tool --timezone UTC --json
```

Run the Intervals.icu plugin directly:

```bash
uv run intervals-icu-tool fitness-status
uv run intervals-icu-tool wellness --date 2026-04-19
uv run intervals-icu-tool weekly-load-progress
uv run intervals-icu-tool activities --oldest 2026-04-01 --newest 2026-04-19 --limit 5
uv run open-meteo-tool search --query "Limassol"
uv run open-meteo-tool forecast --latitude 34.6841 --longitude 33.0379 --hours 12
uv run route-planner-tool point-to-point --start-location "Paphos, Cyprus" --end-location "Limassol, Cyprus" --profile gravel
uv run route-planner-tool round-trip --start-location "Paphos, Cyprus" --max-total-km 60 --max-elevation-m 800 --profile gravel
uv run route-planner-tool strava-auth-url
uv run route-planner-tool strava-exchange --code-or-url "http://localhost/exchange_token?code=..."
uv run route-planner-tool strava-sync
```

## Extend With More Tools

Add a new package under `src/app/plugins/<tool_name>/`, implement a plugin class in `plugin.py`, and register it in `src/app/plugins/loader.py`.

To enable the Intervals.icu, Open-Meteo, and route planner plugins, set:

```bash
APP_ENABLED_PLUGINS=get_time,intervals_icu,open_meteo,route_planner
APP_PUBLIC_BASE_URL=https://agent.example.test
INTERVALS_ICU_API_KEY=...
INTERVALS_ICU_ATHLETE_ID=...
ROUTE_PLANNER_BROUTER_URL=https://brouter.de/brouter
```

If you want round-trip planning to avoid familiar roads using your Strava history, also set:

```bash
STRAVA_CLIENT_ID=...
STRAVA_CLIENT_SECRET=...
STRAVA_REDIRECT_URI=http://localhost/exchange_token
```

To restrict Telegram access to specific accounts, set for example:

```bash
TELEGRAM_AUTHORIZED_USERS=@alice,123456789
```

For Proxmox LXC deployment with boot-time startup, see [deploy/lxc/README.md](/home/anasyrov/Documents/my_projects/1_active_only_one/PydanticAI/deploy/lxc/README.md).
