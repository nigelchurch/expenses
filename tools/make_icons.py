"""Render the app icons (PNG) from inline SVG using Edge via Playwright.
Run:  python tools/make_icons.py
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "icons"

def svg(size: int, maskable: bool) -> str:
    # maskable icons need the artwork inside the central 80% "safe zone"
    radius = 0 if maskable else size * 0.22
    s = 0.62 if maskable else 0.78
    inner = size * s
    off = (size - inner) / 2
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">
  <rect width="{size}" height="{size}" rx="{radius}" fill="#1f6f5c"/>
  <g transform="translate({off},{off}) scale({inner/100})">
    <rect x="18" y="8" width="64" height="84" rx="8" fill="#ffffff"/>
    <path d="M18 84 l8 8 l8 -8 l8 8 l8 -8 l8 8 l8 -8 l8 8 l8 -8 V92 H18z" fill="#1f6f5c" opacity="0"/>
    <rect x="30" y="24" width="40" height="6" rx="3" fill="#1f6f5c"/>
    <rect x="30" y="40" width="40" height="6" rx="3" fill="#9fd3c4"/>
    <rect x="30" y="56" width="26" height="6" rx="3" fill="#9fd3c4"/>
    <circle cx="66" cy="74" r="13" fill="#f2b33d"/>
    <path d="M60 74 h12 M66 68 v12" stroke="#1f6f5c" stroke-width="4" stroke-linecap="round"/>
  </g>
</svg>"""

def main():
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        for name, size, mask in [("icon-192.png", 192, False), ("icon-512.png", 512, False), ("icon-maskable-512.png", 512, True)]:
            pg = b.new_page(viewport={"width": size, "height": size})
            pg.set_content(f"<html><body style='margin:0;background:transparent'>{svg(size, mask)}</body></html>")
            pg.screenshot(path=str(OUT / name), omit_background=True, clip={"x": 0, "y": 0, "width": size, "height": size})
            pg.close()
            print("wrote", OUT / name)
        b.close()

if __name__ == "__main__":
    main()
