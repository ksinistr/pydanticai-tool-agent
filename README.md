# PydanticAI Telegram Bot

Simple Telegram bot built with PydanticAI, an OpenAI-compatible provider, and a small plugin contract that is easy to extend later.

## Features

- Telegram long polling
- Local web chat UI via `Agent.to_web()`
- Explicit plugin loading
- Per-plugin CLI entrypoints for isolated testing
- Example `get_time` tool plugin
- Native Telegram `/morning_report` command with a dedicated PydanticAI morning brief
- Native Telegram `/daily_training_advice` command with a dedicated remaining-day training brief
- Optional `intervals_icu` plugin for wellness, weekly load progress, and activities
- Optional `open_meteo` plugin for geocoding and weather forecasts
- Optional `route_planner` plugin for GPX route generation via BRouter
- Static GPX image rendering with an OpenTopoMap route map and elevation profile
- Optional `caldav` plugin for Baikal-focused calendar discovery and event CRUD via CalDAV

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
- `CALDAV_SERVER_URL` and `CALDAV_USERNAME` if you enable the CalDAV plugin
- `CALDAV_PASSWORD` for CalDAV auth, or `BAIKAL_PASSWORD` as a fallback
- `MORNING_REPORT_LATITUDE`, `MORNING_REPORT_LONGITUDE`, `USER_TIMEZONE`, and `MORNING_REPORT_LANGUAGE` if you want `/morning_report`
- `MORNING_REPORT_HOLIDAYS_CALENDAR_ID` and `MORNING_REPORT_VACATION_CALENDAR_ID` if you want to override the default holiday and vacation calendars used by `/morning_report`
- The same `MORNING_REPORT_*` and `USER_TIMEZONE` values are also used by `/daily_training_advice`; no extra variables are required
- `BROUTER_URL` if you enable the route planner plugin
- `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` if you want route planner to avoid known roads using Strava history

## Run

Start Telegram bot:

```bash
make telegram
```

Inside Telegram, `/morning_report` uses a dedicated morning-report flow and does not depend on the normal chat history.
When CalDAV is configured, `/morning_report` also checks the holiday and vacation calendars before applying weekday workday constraints.
`/daily_training_advice` is a separate flow that uses the same configuration values, but it adjusts the advice to the remaining part of the current local day and accounts for workouts already completed today in Intervals.icu.

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
uv run caldav-tool calendars list
uv run caldav-tool events list --calendar-id personal --from 2026-03-24T00:00:00Z --to 2026-03-31T23:59:59Z
uv run caldav-tool events create --calendar-id personal --title "Team Sync" --start 2026-03-25T09:00:00Z --end 2026-03-25T09:30:00Z --description "Weekly sync"
uv run caldav-tool events update --calendar-id personal --event-id 2026-03-25-team-sync.ics --description "Room 301"
uv run caldav-tool events delete --calendar-id personal --event-id 2026-03-25-team-sync.ics
uv run open-meteo-tool search --query "Limassol"
uv run open-meteo-tool forecast --latitude 34.6841 --longitude 33.0379 --hours 12
uv run route-planner-tool point-to-point --start-location "Paphos, Cyprus" --end-location "Limassol, Cyprus" --profile gravel
uv run route-planner-tool round-trip --start-latitude 34.7750 --start-longitude 32.4240 --max-total-km 60 --max-elevation-m 800 --profile gravel
uv run route-planner-tool render-images --gpx-reference output/route_planner/example.gpx --track-color red
uv run route-planner-tool strava-auth-url
uv run route-planner-tool strava-exchange --code-or-url "http://localhost/exchange_token?code=..."
uv run route-planner-tool strava-sync
```

For round-trip routing, resolve place names to coordinates first, for example with `uv run open-meteo-tool search --query "Paphos"`.
The image renderer can consume a local GPX path or a `/downloads/...` GPX artifact URL returned by the agent.

## Extend With More Tools

Add a new package under `src/app/plugins/<tool_name>/`, implement a plugin class in `plugin.py`, and register it in `src/app/plugins/loader.py`.

To enable the Intervals.icu, Open-Meteo, and route planner plugins, set:

```bash
APP_ENABLED_PLUGINS=get_time,intervals_icu,open_meteo,route_planner
APP_PUBLIC_BASE_URL=https://agent.example.test
INTERVALS_ICU_API_KEY=...
INTERVALS_ICU_ATHLETE_ID=...
BROUTER_URL=https://brouter.de/brouter
BROUTER_WEB_URL=https://brouter.de/brouter-web
```

If you want CalDAV access, also set:

```bash
APP_ENABLED_PLUGINS=get_time,caldav
CALDAV_SERVER_URL=https://baikal.example.test/dav.php/
CALDAV_USERNAME=alice
CALDAV_PASSWORD=...
USER_TIMEZONE=Asia/Nicosia
MORNING_REPORT_HOLIDAYS_CALENDAR_ID=7c61385b-fea4-4469-9067-07c85e977bcb
MORNING_REPORT_VACATION_CALENDAR_ID=78d55081-ba84-4d8d-b873-264c18d0a3c0
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
