#!/usr/bin/env bash
# Builds the zip to send to collaborators: ../RemindMeBro-demo-YYYY-MM-DD.zip (next to the project folder).
# Code + Illia's current data (data/), so whoever opens it sees what is being tried right now.
# Never in the zip: .runtime, node_modules, backups, the AI key (data/ai.env: everyone uses their own key, the Run & Go
# asks for it) and the Whisper model (data/whisper, 140 MB: downloaded again by itself).
# The SQLite databases are copied with SQLite's backup API: consistent even while the app is running.
#
# Usage: ./scripts/make-zip.sh             code + data
#        ./scripts/make-zip.sh --no-data   code only (starts from zero: accounts, the eight courses and their timetable)
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$(dirname "$HERE")"
WITH_DATA=1
[ "${1:-}" = "--no-data" ] && WITH_DATA=0
# on a branch other than main the zip name says which one (RemindMeBro-demo-YYYY-MM-DD-feature-x.zip)
BRANCH="$(git -C "$HERE" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
SUFFIX=""
[ "$BRANCH" != "main" ] && [ "$BRANCH" != "HEAD" ] && SUFFIX="-$(echo "$BRANCH" | tr '/ ' '--')"
[ "$WITH_DATA" = "0" ] && SUFFIX="$SUFFIX-no-data"
NAME="RemindMeBro-demo-$(date +%Y-%m-%d)$SUFFIX.zip"
PY="$(command -v python3 || true)"
[ -z "$PY" ] && [ -x "$HERE/.runtime/venv/bin/python" ] && PY="$HERE/.runtime/venv/bin/python"
[ -z "$PY" ] && { echo "python3 not found"; exit 1; }
"$PY" - "$HERE" "$OUT_DIR/$NAME" "$WITH_DATA" <<'PYEOF'
import os, sqlite3, stat, sys, tempfile, zipfile, datetime
root, out, with_data = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
INCLUDE = ["README.md", "config", "app", "frontend", "scripts", "unilearn", "unisis", "unicomms", "web", "docs"]
INCLUDE += sorted(f for f in os.listdir(root) if f.startswith("run-"))
SKIP_DIRS = {"__pycache__", "node_modules", ".runtime", "data", "dist", ".git", "_to_delete"}
# in data/: never the AI key, never the Whisper model; SQLite side files are not needed (the copy is complete)
DATA_SKIP_FILES = {"ai.env"}
DATA_SKIP_DIRS = {"whisper", "__pycache__"}
DB_EXT = (".db", ".sqlite3", ".sqlite")
n = 0
tmp = out + ".part"


def add_file(z, path, arcname):
    global n
    info = zipfile.ZipInfo.from_file(path, arcname)
    info.compress_type = zipfile.ZIP_DEFLATED
    if path.endswith((".sh", ".command", ".bat")):
        info.external_attr = (0o755 | stat.S_IFREG) << 16   # launchers stay double-clickable
    with open(path, "rb") as fh:
        z.writestr(info, fh.read())
    n += 1


def add_database(z, path, arcname):
    """A consistent copy of a SQLite database, also while the app is writing to it (WAL included)."""
    global n
    with tempfile.TemporaryDirectory() as tmpdir:
        copy = os.path.join(tmpdir, "copy.db")
        src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        dst = sqlite3.connect(copy)
        with dst:
            src.backup(dst)
        src.close()
        dst.execute("PRAGMA journal_mode=DELETE")   # one self-contained file
        dst.close()
        z.write(copy, arcname, compress_type=zipfile.ZIP_DEFLATED)
    n += 1


data_files = 0
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
                add_file(z, path, "RemindMeBro/" + os.path.relpath(path, root))
    data = os.path.join(root, "data")
    if with_data and os.path.isdir(data):
        for base, dirs, files in os.walk(data):
            dirs[:] = [d for d in dirs if d not in DATA_SKIP_DIRS]
            for f in files:
                if f in DATA_SKIP_FILES or f.endswith(("-wal", "-shm", "-journal", ".part", ".log")) or f == ".DS_Store":
                    continue
                path = os.path.join(base, f)
                arc = "RemindMeBro/" + os.path.relpath(path, root)
                if f.endswith(DB_EXT):
                    add_database(z, path, arc)
                else:
                    add_file(z, path, arc)
                data_files += 1
    note = ("Data: included (data/), without the AI key and the Whisper model.\n" if with_data and data_files
            else "Data: not included: the app starts from zero.\n")
    z.writestr("RemindMeBro/BUILD.txt", f"Remind Me Bro demo\nZip made on {datetime.datetime.now():%Y-%m-%d %H:%M}\n{note}"
                                        "Start: open docs/START-HERE.txt\n")
os.replace(tmp, out)
print(f"{out}  ({n} files, {data_files} from data/, {os.path.getsize(out) // 1024} KB)")
PYEOF
