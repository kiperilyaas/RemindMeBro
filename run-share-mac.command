#!/bin/bash
# Double-click me on macOS: starts the app AND a public link (ngrok) with a QR code for friends.
cd "$(dirname "$0")" && RMB_SHARE=1 exec /bin/bash scripts/run.sh "$@"
