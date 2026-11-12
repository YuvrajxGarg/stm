"""Renders Stm's icon: "stm" in a heavy grotesk with four lime track lines, one per stem,
on the same dark tile as the Dwn and Tag icons.

    python tools/make_icon.py      # needs playwright (Chromium) and Pillow

Writes assets/icon.png (1024), assets/icon.ico, assets/AppIcon.icns and docs/icon-256.png.
"""
import io
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HTML = """<!doctype html><html><head><style>
html, body { margin: 0; background: transparent; }
.tile { position: absolute; left: 100px; top: 88px; width: 824px; height: 824px; border-radius: 185px;
  background: linear-gradient(#2b2b2d, #121213); box-shadow: inset 0 0 0 2px rgba(255,255,255,.14), 0 16px 40px rgba(0,0,0,.45);
  display: flex; align-items: center; justify-content: center; }
.mark { display: flex; align-items: baseline; font: 900 290px/1 "Inter Display", "SF Pro Display", sans-serif;
  letter-spacing: -.055em; color: #fff; margin-top: -30px; }
.bars { display: inline-block; width: 150px; margin-left: 24px; vertical-align: baseline; }
.bars b { height: 23px; border-radius: 12px; background: #ccff4d; display: block; }
.bars b + b { margin-top: 22px; }
</style></head><body>
<div class="tile"><div class="mark">stm<span class="bars"><b style="width:100%"></b><b style="width:60%"></b><b style="width:85%"></b><b style="width:42%"></b></span></div></div>
</body></html>"""


def main():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        exe = os.environ.get("CHROMIUM")
        b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        page = b.new_page(viewport={"width": 1024, "height": 1024})
        page.set_content(HTML)
        page.wait_for_timeout(300)
        png = page.screenshot(omit_background=True)
        b.close()
    im = Image.open(io.BytesIO(png)).convert("RGBA")
    im.save(os.path.join(ROOT, "assets", "icon.png"))
    im.resize((256, 256), Image.LANCZOS).save(os.path.join(ROOT, "docs", "icon-256.png"))
    im.save(os.path.join(ROOT, "assets", "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    im.save(os.path.join(ROOT, "assets", "AppIcon.icns"))
    print("icons written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
