# VoiceStudio

Upstream: https://github.com/debpalash/VoiceStudio · image `ghcr.io/debpalash/voicestudio:stable`
(GPU service from upstream `deploy/docker-compose.yml`, with the GPU requested via CDI and analytics disabled).

## First open

Click **Open**; no key is asked for. The proxy in `catalog/_autologin` adds the admin key for your browser.

The first start downloads about 4 GB of models into the `voicestudio-data` volume; the tile shows
"Starting…" until the app answers. 6 GB VRAM is enough (TTS offloads to CPU when needed).

## Manual check

Clone a voice from a ~10 s sample, then speak a sentence with it.
