# OpenHands

Upstream: https://github.com/OpenHands/OpenHands · image `ghcr.io/openhands/agent-canvas:1.34.0`
(upstream README "Option 2: With a Docker Sandbox" — the container itself is the sandbox, so no
container socket is mounted).

## First open

1. Click **Open** (goes to `/canvas`); no key is asked for. The proxy in `catalog/_autologin` adds it to the page.
2. In OpenHands settings, choose an LLM provider and paste its API key.

Projects the agent works on live in the `openhands-projects` volume (`/projects` inside the app).

## Manual check

Start a conversation: "create hello.py that prints the date, then run it" — the agent writes and runs it.
