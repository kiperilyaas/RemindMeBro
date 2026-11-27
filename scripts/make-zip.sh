#!/usr/bin/env bash
# Builds the zip to send to collaborators: ../RemindMeBro-demo-YYYY-MM-DD.zip (next to the project folder).
# Only what is needed to run the demo: no .runtime, no data, no backups, no node_modules.
# Usage: ./scripts/make-zip.sh        (from the project folder, or anywhere)
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$(dirname "$HERE")"
# on a branch other than main the zip name says which one (RemindMeBro-demo-YYYY-MM-DD-feature-x.zip)
BRANCH="$(git -C "$HERE" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
SUFFIX=""
[ "$BRANCH" != "main" ] && [ "$BRANCH" != "HEAD" ] && SUFFIX="-$(echo "$BRANCH" | tr '/ ' '--')"
NAME="RemindMeBro-demo-$(date +%Y-%m-%d)$SUFFIX.zip"
PY="$(command -v python3 || true)"
[ -z "$PY" ] && [ -x "$HERE/.runtime/venv/bin/python" ] && PY="$HERE/.runtime/venv/bin/python"
[ -z "$PY" ] && { echo "python3 not found"; exit 1; }
"$PY" - "$HERE" "$OUT_DIR/$NAME" <<'PYEOF'
import os, stat, sys, zipfile, datetime
root, out = sys.argv[1], sys.argv[2]
INCLUDE = ["README.md", "START-HERE.txt", "ai.env.example", "requirements.txt", "requirements-whisper.txt", "app", "frontend", "scripts", "unilearn", "unisis", "unicomms", "web", "docs"]
INCLUDE += sorted(f for f in os.listdir(root) if f.startswith("run-"))
SKIP_DIRS = {"__pycache__", "node_modules", ".runtime", "data", "dist", ".git", "_to_delete"}
n = 0
tmp = out + ".part"
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
    for item in INCLUDE:
        top = os.path.join(root, item)
        if not os.path.exists(top):
            continue
        walk = [(os.path.dirname(top), [], [item])] if os.path.isfile(top) else os.walk(top)
        for base, dirs, files in walk:
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith("_backup")]
            for f in files:
                if f.endswith((".pyc", ".log")) or f == ".DS_Store" or ".timestamp-" in f:
                    continue
                path = os.path.join(base, f)
                info = zipfile.ZipInfo.from_file(path, "RemindMeBro/" + os.path.relpath(path, root))
                info.compress_type = zipfile.ZIP_DEFLATED
                if f.endswith((".sh", ".command", ".bat")):
                    info.external_attr = (0o755 | stat.S_IFREG) << 16   # launchers stay double-clickable
                with open(path, "rb") as fh:
                    z.writestr(info, fh.read())
                n += 1
    z.writestr("RemindMeBro/BUILD.txt", f"Remind Me Bro demo\nZip made on {datetime.datetime.now():%Y-%m-%d %H:%M}\nStart: open START-HERE.txt\n")
os.replace(tmp, out)
print(f"{out}  ({n} files, {os.path.getsize(out) // 1024} KB)")
PYEOF
