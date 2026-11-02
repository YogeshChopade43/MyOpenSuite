# Next AI Draw.io

Upstream: https://github.com/DayuanJiang/next-ai-draw-io · image `ghcr.io/dayuanjiang/next-ai-draw-io:latest`

## AI provider (until the LLM Gateway lands)

The app needs an AI provider to generate diagrams. Open the app, go to **Settings**, choose a provider
(OpenRouter, Anthropic, OpenAI, …) and paste your API key. Settings persist in the `drawio-data` volume.

Once the gateway milestone is done, MyOpenSuite will inject the gateway URL and key automatically.

## Manual check

Open the app, type "flowchart of a user signing up and confirming their email", and an editable
diagram appears on the canvas.
