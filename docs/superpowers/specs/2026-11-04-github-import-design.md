# Import an app from a GitHub link

The owner pastes a GitHub link in the Marketplace, reviews what was found, and installs it like any catalog app.

## Flow

1. `POST /api/import/preview {url}`: reads the repo and returns name, licence, stars, how it will run, port,
   warnings and blockers. Writes nothing.
2. `POST /api/import {url, sha, replaces}`: repeats the check at the reviewed commit, writes the entry to
   `$MOS_STATE/catalog/<id>/` and adds it to the live catalog. The UI then calls the normal install.

Imported apps survive dashboard rebuilds. Uninstalling one also removes it from the catalog.

## Where the setup comes from, best first

1. A compose file with one service and an image.
2. A `docker run` line in the README.
3. A compose file with one service that builds from source.
4. A Dockerfile at the root.

Build sources download the repo tarball at the reviewed commit and carry a warning: slow, heavy on RAM and disk.
Anything else is refused with a clear message, including multi-container stacks. Those needed hand fixes (AppFlowy).

## Conversion

- One service, named after the repo, on `mos-net`, published on a free localhost port from 7810.
- Only known-safe service keys are kept. The healthcheck is dropped, restart is `unless-stopped`.
- Host folders become named volumes; single config files are dropped with a warning.
- Password-like settings that are empty or placeholders become generated secrets.
- GPU requests are dropped with a warning, so imports run on the CPU.
- `lint_compose` must pass, or the import is refused and nothing is kept.

## Security

- Only `https://github.com/<owner>/<repo>`. Every fetched URL is built from those validated parts.
- Refused with no override: the container socket, privileged mode, host networking, host PID or IPC, devices,
  SYS_ADMIN or ALL capabilities, unconfined security options, build contexts outside the repo.
- The licence is shown; anything not clearly open source gets a warning.
- The compose file is stored at import, and nothing changes until the owner presses Update. A `latest` image tag
  can still move on Update, and the review screen says so.
- Plain rules only, no AI, in line with the no-Claude decision.

## Not covered

Multi-container stacks, auto-login, access to the owner's own folders, desktop apps and libraries.

## Test

Unit tests cover parsing, conversion and every refusal. Real end-to-end tests run only on repos above 20k stars
that do not need a GPU, one at a time, because of this PC's memory limit.
