#!/bin/bash
# Double-click me on macOS: installs what is missing, starts the app and opens the browser.
# Same as run-share-mac.command in the main folder, without the public link.
cd "$(dirname "$0")/.." && exec /bin/bash scripts/run.sh "$@"
