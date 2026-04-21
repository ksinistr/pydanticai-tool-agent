.PHONY: install format lint test run-both telegram web tool-caldav tool-get-time tool-route-planner

UV_CACHE_DIR := .uv-cache

install:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv sync --all-groups

format:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run ruff format .

lint:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run ruff check .

test:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run pytest

run-both:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run agent-all

telegram:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run telegram-bot

web:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run agent-web

tool-get-time:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run get-time-tool

tool-caldav:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run caldav-tool --help

tool-route-planner:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run route-planner-tool --help
