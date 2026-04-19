# LXC Deployment

Recommended for a Proxmox LXC container:

- run the app directly inside the container
- use `systemd` for boot-time startup and restarts
- run the service as a dedicated Unix user
- start the installed `.venv/bin/agent-all` entrypoint, not `make run-both`

This keeps boot startup predictable and avoids rebuilding or resolving dependencies on every restart.

## Layout

- app directory: `/opt/pydanticai-tool-agent`
- env file: `/etc/pydanticai-tool-agent/pydanticai-tool-agent.env`
- service file: `/etc/systemd/system/pydanticai-tool-agent.service`
- service user: `pydanticai`

## One-Time Setup

Install Python 3.11+ and `uv` in the container first.

Create a dedicated user and directories:

```bash
useradd --system --create-home --shell /usr/sbin/nologin pydanticai
install -d -o pydanticai -g pydanticai /opt/pydanticai-tool-agent
install -d -o root -g root /etc/pydanticai-tool-agent
```

Clone the repo and install dependencies:

```bash
git clone <REPO_URL> /opt/pydanticai-tool-agent
cd /opt/pydanticai-tool-agent
uv sync --frozen --all-groups
chown -R pydanticai:pydanticai /opt/pydanticai-tool-agent
```

Install the env file:

```bash
install -m 600 deploy/lxc/pydanticai-tool-agent.env.example /etc/pydanticai-tool-agent/pydanticai-tool-agent.env
editor /etc/pydanticai-tool-agent/pydanticai-tool-agent.env
```

If you want to restrict Telegram access, set `TELEGRAM_AUTHORIZED_USERS` in that env file with a comma-separated list of usernames or numeric Telegram user IDs.

Install and enable the service:

```bash
install -m 644 deploy/lxc/systemd/pydanticai-tool-agent.service /etc/systemd/system/pydanticai-tool-agent.service
systemctl daemon-reload
systemctl enable --now pydanticai-tool-agent.service
```

## Updates

```bash
cd /opt/pydanticai-tool-agent
git pull
uv sync --frozen --all-groups
systemctl restart pydanticai-tool-agent.service
```

## Useful Commands

```bash
systemctl status pydanticai-tool-agent.service
journalctl -u pydanticai-tool-agent.service -f
systemctl restart pydanticai-tool-agent.service
systemctl stop pydanticai-tool-agent.service
```

## Why This Instead Of `make run-both`

`make run-both` is fine for interactive local use.

For always-on startup inside LXC, `systemd` should start the already installed binary entrypoint:

```bash
/opt/pydanticai-tool-agent/.venv/bin/agent-all
```

That avoids `make`, avoids `uv run`, and keeps runtime startup separate from build and dependency management.
