"""Test stand-in for RBA Web Site's page kit render.py (same interface):
render.py CATALOG.json OUT_DIR. Exits 1 and writes nothing on a refused
catalog. FAKE_KIT_REFUSE=1 refuses; FAKE_KIT_CSS changes the stylesheet's
bytes without changing its fingerprinted name (to test the never-overwrite
check)."""
import json
import os
import sys

catalog_path, out = sys.argv[1], sys.argv[2]
with open(catalog_path, encoding="utf-8") as f:
    catalog = json.load(f)
if os.environ.get("FAKE_KIT_REFUSE") or catalog.get("schema") != 1:
    print("fake kit: refused", file=sys.stderr)
    sys.exit(1)
files = {
    "_kit/kit.0123456789.css": os.environ.get("FAKE_KIT_CSS", "body{color:#e8e6e3}\n").encode(),
    "_kit/space-grotesk-400.abcdef0123.woff2": b"wOF2fake",
    "index.html": f'<link rel="stylesheet" href="/_kit/kit.0123456789.css"><h1>{len(catalog["products"])} products</h1>\n'.encode(),
}
for p in catalog["products"]:
    files[f"{p['id']}/index.html"] = f"<h1>{p['name']} {p['latest_version']}</h1>\n".encode()
for rel, body in files.items():
    path = os.path.join(out, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(body)
