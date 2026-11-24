#!/usr/bin/env bash
# Run me on Linux (./run-share-linux.sh): starts the app AND a public link (ngrok) with a QR code for friends.
cd "$(dirname "$0")" && RMB_SHARE=1 exec bash scripts/run.sh "$@"
