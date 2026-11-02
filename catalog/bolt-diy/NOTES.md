# bolt.diy

Upstream: https://github.com/stackblitz-labs/bolt.diy · image `ghcr.io/stackblitz-labs/bolt.diy:stable`
(the release-tracking tag; upstream publishes no versioned image tags). Started with upstream's
production command `pnpm run dockerstart`.

## AI provider

Open the app, pick a provider (OpenAI, Anthropic, OpenRouter, Google, Ollama, …) next to the chat box
and paste its API key. Keys are kept in your browser.

## Manual check

Ask for "a todo app in React"; the files appear and the preview pane runs it (in-browser WebContainers).

## Notes

- The preview pane uses StackBlitz WebContainers, which the browser downloads from
  `*.staticblitz.com` — the preview needs internet access even though the app is self-hosted.
- The console shows a harmless "Failed to fetch local package.json" from bolt.diy's update checker.
- `icon.png` is upstream's `favicon.svg` rendered at 256 px (the PNG logos are wide wordmarks).
