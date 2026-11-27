#!/usr/bin/env bash
# Run me on Linux (./scripts/run-linux.sh): installs what is missing, starts the app and opens the browser.
# Same as run-share-linux.sh in the main folder, without the public link.
cd "$(dirname "$0")/.." && exec bash scripts/run.sh "$@"
