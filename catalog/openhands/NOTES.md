# OpenHands

Upstream: https://github.com/OpenHands/OpenHands · image `ghcr.io/openhands/agent-canvas:1.34.0`
(upstream README "Option 2: With a Docker Sandbox" — the container itself is the sandbox, so no
container socket is mounted).

## First open

1. In MyOpenSuite, click **Credentials** on the OpenHands tile and copy the login key.
2. Click **Open** (goes to `/canvas`) and paste the key.
3. In OpenHands settings, choose an LLM provider and paste its API key.

Projects the agent works on live in the `openhands-projects` volume (`/projects` inside the app).

## Manual check

Start a conversation: "create hello.py that prints the date, then run it" — the agent writes and runs it.
