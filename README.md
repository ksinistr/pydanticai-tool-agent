# PydanticAI Telegram Bot

Simple Telegram bot built with PydanticAI, OpenRouter, and a small plugin contract that is easy to extend later.

## Features

- Telegram long polling
- Local web chat UI via `Agent.to_web()`
- Explicit plugin loading
- Per-plugin CLI entrypoints for isolated testing
- Example `get_time` tool plugin
- Optional `intervals_icu` plugin for wellness, weekly load progress, and activities
- Optional `open_meteo` plugin for geocoding and weather forecasts

## Setup

1. Copy `.env.example` to `.env` or export the variables in your shell.
2. Install dependencies:

```bash
make install
```

3. Set these variables:

- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`
- `TELEGRAM_BOT_TOKEN` for Telegram mode
- `INTERVALS_ICU_API_KEY` and `INTERVALS_ICU_ATHLETE_ID` if you enable the Intervals.icu plugin

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
```

## Extend With More Tools

Add a new package under `src/app/plugins/<tool_name>/`, implement a plugin class in `plugin.py`, and register it in `src/app/plugins/loader.py`.

To enable the Intervals.icu plugin, set:

```bash
APP_ENABLED_PLUGINS=get_time,intervals_icu,open_meteo
INTERVALS_ICU_API_KEY=...
INTERVALS_ICU_ATHLETE_ID=...
```
