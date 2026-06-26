# Docling Server Setup

FastAPI server that parses documents (PDF, DOCX, etc.) using Docling and returns structured markdown.

Runs on port `7777`.

## Requirements

- macOS with Apple Silicon (MPS acceleration) or Intel (CPU fallback)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

## Running manually

```sh
uv run server.py
```

## Running on startup (macOS LaunchAgent)

Suitable for a Mac mini with auto-login enabled. The server starts at login and restarts automatically if it crashes.

**1. Edit the plist**

Open `com.alai.docling-server.plist` and replace `YOUR_USERNAME` with your macOS username (check with `whoami`).

If `uv` is not at `/opt/homebrew/bin/uv` (e.g. Intel Mac), update that path too:

```sh
which uv
```

**2. Install the plist**

```sh
cp com.alai.docling-server.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.alai.docling-server.plist
```

**3. Verify it's running**

```sh
launchctl list | grep docling
curl http://localhost:7777/health
```

**4. View logs**

```sh
tail -f ~/Library/Logs/docling-server.log
```

## Common commands

```sh
# Stop
launchctl stop com.alai.docling-server

# Start
launchctl start com.alai.docling-server

# Disable autostart
launchctl unload ~/Library/LaunchAgents/com.alai.docling-server.plist
```

## Resource sharing with Ollama

This server uses Apple Silicon MPS for GPU-accelerated PDF parsing. If Ollama is also running on the same machine, both share the unified memory pool.

With 24 GB RAM and a model like qwen3-8b (~5–6 GB), both services can stay loaded simultaneously with comfortable headroom (~7–9 GB free at peak).

To avoid memory pressure during concurrent heavy use, set Ollama's keep-alive to unload models when idle:

```sh
OLLAMA_KEEP_ALIVE=30m ollama serve
```
