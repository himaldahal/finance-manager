#!/usr/bin/env python3
"""Build app/static/app/icons/sprite.svg from the Lucide icon pack.

Development-time only: downloads the pinned release once. The running
application never contacts any third party.

    python scripts/build_icons.py
"""
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.icons import ALL_ICONS  # noqa: E402

VERSION = "0.468.0"
BASE = f"https://unpkg.com/lucide-static@{VERSION}"
OUT = ROOT / "app" / "static" / "app" / "icons"


def fetch(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    symbols, failed = [], []
    for name in ALL_ICONS:
        try:
            source = fetch(f"{BASE}/icons/{name}.svg")
        except Exception as exc:  # noqa: BLE001
            failed.append((name, str(exc)))
            continue
        inner = re.search(r"<svg[^>]*>(.*)</svg>", source, re.S).group(1)
        inner = re.sub(r"\s+", " ", inner).strip()
        symbols.append(f'<symbol id="{name}" viewBox="0 0 24 24">{inner}</symbol>')
    sprite = (
        '<svg xmlns="http://www.w3.org/2000/svg" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">\n' + "\n".join(symbols) + "\n</svg>\n"
    )
    (OUT / "sprite.svg").write_text(sprite, encoding="utf-8")
    licence = fetch(f"{BASE}/LICENSE")
    (OUT / "LICENSE").write_text(
        f"Icons are from Lucide (lucide-static {VERSION}), https://lucide.dev\n\n{licence}", encoding="utf-8")
    print(f"wrote {len(symbols)} icons")
    for name, error in failed:
        print("FAILED", name, error)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
