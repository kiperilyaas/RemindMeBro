"""
Remind Me Bro - share with friends.

Waits for the ngrok tunnel, then:
  * prints a QR code of the public link in the terminal (black on white, any background),
  * writes <out>/qr.html (big QR code + link, ready to show on screen),
  * writes <out>/url.txt with the link.

Usage: python scripts/share.py --out .runtime/share [--log .runtime/logs/ngrok.log] [--timeout 40]
Exit codes: 0 ok, 2 tunnel not found (ngrok error or timeout).
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

import qrcode


def find_public_url(log: Path | None, timeout: float) -> str:
    end = time.time() + timeout
    while time.time() < end:
        for port in range(4040, 4046):   # ngrok's local API (4041+ if 4040 is busy)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tunnels", timeout=2) as r:
                    data = json.load(r)
            except Exception:
                continue
            urls = [t.get("public_url", "") for t in data.get("tunnels", [])]
            https = [u for u in urls if u.startswith("https://")]
            if https or urls:
                return (https or urls)[0]
        if log and log.exists():
            text = log.read_text(errors="replace")
            err = re.search(r"(ERR_NGROK_\d+)", text)
            if err:
                msg = re.search(r'err="([^"]+)', text)
                raise SystemExit(f"ngrok error {err.group(1)}: {msg.group(1) if msg else 'see ' + str(log)}")
        time.sleep(0.5)
    raise SystemExit("ngrok did not give a public link in time")


def matrix(url: str) -> list[list[bool]]:
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.get_matrix()


def print_qr(m: list[list[bool]]) -> None:
    if os.name == "nt":
        os.system("")   # turns on ANSI colours in the Windows console
    # two QR rows per text line: upper half block, foreground = top cell, background = bottom cell
    fg = {True: "\033[30m", False: "\033[97m"}
    bg = {True: "\033[40m", False: "\033[107m"}
    rows = m + ([[False] * len(m[0])] if len(m) % 2 else [])
    for i in range(0, len(rows), 2):
        line = "".join(fg[t] + bg[b] + "▀" for t, b in zip(rows[i], rows[i + 1]))
        print("    " + line + "\033[0m")


def svg(m: list[list[bool]], scale: int = 10) -> str:
    n = len(m)
    rects = "".join(
        f'<rect x="{x}" y="{y}" width="1" height="1"/>' for y, row in enumerate(m) for x, v in enumerate(row) if v
    )
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" width="{n * scale}" height="{n * scale}" '
            f'shape-rendering="crispEdges"><rect width="{n}" height="{n}" fill="#fff"/><g fill="#000">{rects}</g></svg>')


PAGE = """<!doctype html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Remind Me Bro · link per gli amici</title>
<style>
 body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f4f5;color:#18181b;display:flex;min-height:100vh;align-items:center;justify-content:center}}
 main{{background:#fff;border:1px solid #e4e4e7;border-radius:16px;padding:32px 40px;text-align:center;max-width:520px}}
 h1{{font-size:22px;margin:0 0 4px}} p{{color:#52525b;line-height:1.5;margin:8px 0}}
 svg{{width:min(340px,80vw);height:auto;margin:16px 0}}
 .link{{display:flex;gap:8px;align-items:center;justify-content:center;margin-top:8px}}
 code{{background:#f4f4f5;border:1px solid #e4e4e7;border-radius:8px;padding:8px 10px;font-size:14px;word-break:break-all}}
 button{{border:0;background:#18181b;color:#fff;border-radius:8px;padding:9px 14px;font-size:14px;cursor:pointer}}
 small{{display:block;color:#71717a;margin-top:18px;line-height:1.5}}
</style></head><body><main>
{logo}
<p>Inquadra il QR code con la fotocamera del telefono.</p>
{svg}
<div class="link"><code id="u">{url}</code><button onclick="navigator.clipboard.writeText(document.getElementById('u').textContent);this.textContent='Copiato'">Copia</button></div>
<small>Se compare la pagina di ngrok, premi <b>Visit Site</b>.<br>
Premi <b>Create account</b> e crea il tuo account studente: ricevi anche UniSIS e UniLearn, già collegati.<br>
Il link funziona finché la finestra nera resta aperta su questo computer. A ogni avvio il link cambia.</small>
</main></body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--log")
    ap.add_argument("--timeout", type=float, default=40)
    ap.add_argument("--url", help="skip ngrok and use this link (for tests)")
    a = ap.parse_args()

    try:
        url = a.url or find_public_url(Path(a.log) if a.log else None, a.timeout)
    except SystemExit as e:
        print(f"    {e}", file=sys.stderr)
        sys.exit(2)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    m = matrix(url)
    logo_file = Path(__file__).resolve().parent.parent / "frontend" / "brand" / "logo-light-bg.png"
    logo = (f'<img src="data:image/png;base64,{base64.b64encode(logo_file.read_bytes()).decode()}" alt="Remind Me Bro" style="width:220px;height:auto">'
            if logo_file.exists() else "<h1>Remind Me Bro</h1>")
    (out / "qr.html").write_text(PAGE.format(svg=svg(m), url=html.escape(url), logo=logo), encoding="utf-8")
    (out / "url.txt").write_text(url + "\n", encoding="utf-8")

    print()
    print_qr(m)
    print()
    print(f"    Link for friends:  {url}")
    print(f"    QR code page:      {out / 'qr.html'}")


if __name__ == "__main__":
    main()
