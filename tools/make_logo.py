"""Make the small in-app Nova logo (light, transparent background) from the blue-on-white original.
Run:  python tools/make_logo.py "path/to/Nova Embedded Solutions.png"
"""
import base64, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "icons" / "nova.png"
SIZE, COLOUR = 288, (201, 210, 207)  # 3x the 96px it is shown at

JS = """async ([src, size, rgb]) => {
  const img = new Image(); img.src = src; await img.decode();
  const cv = (w, h) => Object.assign(document.createElement('canvas'), { width: w, height: h });
  const a = cv(img.width, img.height), ca = a.getContext('2d');
  ca.fillStyle = '#fff'; ca.fillRect(0, 0, a.width, a.height); ca.drawImage(img, 0, 0);
  const d = ca.getImageData(0, 0, a.width, a.height);
  let x0 = a.width, y0 = a.height, x1 = 0, y1 = 0;
  for (let i = 0; i < d.data.length; i += 4) {
    const ink = 255 - d.data[i]; // blue ink has no red, white paper has full red
    d.data.set([...rgb, ink], i);
    if (ink > 40) { const x = i / 4 % a.width, y = Math.floor(i / 4 / a.width);
      x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
  }
  ca.putImageData(d, 0, 0);
  const w = x1 - x0 + 1, h = y1 - y0 + 1, k = size / Math.max(w, h);
  const b = cv(size, size), cb = b.getContext('2d');
  cb.imageSmoothingQuality = 'high';
  cb.drawImage(a, x0, y0, w, h, (size - w * k) / 2, (size - h * k) / 2, w * k, h * k);
  return b.toDataURL('image/png');
}"""

src = "data:image/png;base64," + base64.b64encode(Path(sys.argv[1]).read_bytes()).decode()
with sync_playwright() as p:
    br = p.chromium.launch(channel="msedge")
    page = br.new_page()
    OUT.write_bytes(base64.b64decode(page.evaluate(JS, [src, SIZE, list(COLOUR)]).split(",")[1]))
    br.close()
print(OUT, OUT.stat().st_size, "bytes")
