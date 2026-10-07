#!/usr/bin/env python3
"""Render software.rustybucket.ai from catalog.json (root ADR-020; RBA Web Site's
page kit, vendored into rba-infra at a pinned commit).

  render.py CATALOG.json OUT_DIR

Writes OUT_DIR/index.html (every product), OUT_DIR/<product>/index.html (one
product each) and OUT_DIR/_kit/ (CSS, fonts, icons, licences, all fingerprinted
as name.<hash>.ext, so a publish only ever adds new keys). Python 3 stdlib only;
no JavaScript in the output; every asset is same-origin. The page needs:

  Content-Security-Policy: default-src 'none'; img-src 'self'; style-src 'self';
    font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none';
    upgrade-insecure-requests

Product display data (tagline, pitch, icon, accent) is in products.json next to
this file; a product without display data still renders, with its catalog name.
The catalog format: rba-infra docs/architecture/catalog.md (schema 1).
"""
import datetime
import hashlib
import html
import json
import os
import re
import sys

KIT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(KIT, "assets")
SITE = "https://software.rustybucket.ai/"
HOME = "https://rustybucket.ai/"
OS_GROUPS = [("linux", "Linux"), ("windows", "Windows"), ("macos", "macOS"), ("any", "Web")]
ACCENTS = {"violet", "magenta", "cyan", "rust", "lime"}
HEX = {40: re.compile(r"^[0-9A-F]{40}$"), 64: re.compile(r"^[0-9a-f]{64}$")}

e = lambda s: html.escape(str(s), quote=True)


class CatalogError(ValueError):
    pass


# ---- checks ----------------------------------------------------------------

def check_url(url, where):
    if not isinstance(url, str) or not url.startswith(SITE):
        raise CatalogError(f"{where}: URL outside {SITE}")
    return url


def check(catalog):
    """Refuse a catalog the page can't render safely (raises CatalogError)."""
    if catalog.get("schema") != 1:
        raise CatalogError("schema must be 1")
    if not catalog.get("products"):
        raise CatalogError("no products")
    for p in catalog["products"]:
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", p.get("id", "")):
            raise CatalogError(f"bad product id {p.get('id')!r}")
        if not HEX[40].match(p.get("key_fingerprint", "")):
            raise CatalogError(f"{p['id']}: bad key fingerprint")
        check_url(p.get("key_url"), f"{p['id']} key_url")
        versions = p.get("versions") or []
        if not versions or versions[0]["version"] != p.get("latest_version"):
            raise CatalogError(f"{p['id']}: versions[0] must be latest_version")
        for v in versions:
            for key in ("url", "checksums_url", "checksums_sig_url"):
                check_url(v.get(key), f"{p['id']} {v['version']} {key}")
            for f in v.get("files", []):
                where = f"{p['id']} {v['version']} {f.get('name')}"
                for key in ("url", "sig_url"):
                    check_url(f.get(key), f"{where} {key}")
                if not HEX[64].match(f.get("sha256", "")) or not isinstance(f.get("size"), int):
                    raise CatalogError(f"{where}: bad sha256 or size")
        for pid, alias in (p.get("latest") or {}).items():
            check_url(alias.get("url"), f"{p['id']} latest {pid}")
            check_url(alias.get("sig_url"), f"{p['id']} latest {pid} sig")


# ---- formatting -------------------------------------------------------------

def size(n):
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{max(n / 1e3, 0.1):.1f} KB"


def day(iso):
    try:
        d = datetime.date.fromisoformat(iso)
    except (TypeError, ValueError):
        return e(iso)
    return f"{d.day} {d.strftime('%b')} {d.year}"


def fingerprint(fpr):
    return " ".join(fpr[i:i + 4] for i in range(0, 40, 4))


def badge(version):
    if not version.get("prerelease"):
        return ""
    return f'<span class="badge">{"RC" if "-rc" in version["version"] else "Pre-release"}</span>'


# ---- assets -------------------------------------------------------------------

def write_assets(out):
    """Copy the kit's assets into out/_kit/ fingerprinted; returns {logical: url}."""
    os.makedirs(os.path.join(out, "_kit"), exist_ok=True)
    urls = {}

    def put(rel, data):
        name, ext = os.path.splitext(os.path.basename(rel))
        digest = hashlib.sha256(data).hexdigest()[:10]
        target = f"{name}.{digest}{ext}"
        with open(os.path.join(out, "_kit", target), "wb") as fh:
            fh.write(data)
        urls[os.path.basename(rel)] = f"/_kit/{target}"

    for rel in sorted(os.listdir(ASSETS)):
        if not rel.endswith(".css"):
            with open(os.path.join(ASSETS, rel), "rb") as fh:
                put(rel, fh.read())
    css = ""
    for rel in ("colors.css", "spacing.css", "typography.css"):
        with open(os.path.join(ASSETS, rel), encoding="utf-8") as fh:
            css += fh.read()
    with open(os.path.join(KIT, "kit.css"), encoding="utf-8") as fh:
        css += fh.read()
    css = re.sub(r"url\(/_kit/([\w.-]+)\)", lambda m: f"url({urls[m.group(1)]})", css)
    put("kit.css", css.encode("utf-8"))
    return urls


# ---- rendering -------------------------------------------------------------

def display(products, p):
    d = dict(products.get(p["id"], {}))
    d.setdefault("tagline", "")
    d.setdefault("pitch", "")
    if d.get("accent") not in ACCENTS:
        d["accent"] = "violet"
    return d


def icon(d, urls):
    if not d.get("icon"):
        return '<span class="product-icon product-icon-blank" aria-hidden="true"></span>'
    small, large = urls[f"{d['icon']}-96.webp"], urls[f"{d['icon']}-192.webp"]
    return (f'<img class="product-icon" src="{small}" srcset="{small} 96w, {large} 192w" '
            f'sizes="96px" width="96" height="96" alt="">')


def file_row(f, alias):
    note = f'<span class="dl-note">{e(f["note"])}</span>' if f.get("note") else ""
    stable = (f' · <a href="{e(alias["url"])}">stable link</a>' if alias else "")
    return (f'<li class="file">\n'
            f'  <a class="dl" href="{e(f["url"])}"><span class="dl-label">{e(f["label"])}</span>'
            f'<span class="dl-meta">{e(f["arch"])} · {size(f["size"])}</span></a>{note}\n'
            f'  <p class="sum"><span class="sum-label">SHA-256</span> <code class="sha">{e(f["sha256"])}</code></p>\n'
            f'  <p class="sig"><a href="{e(f["sig_url"])}">Signature (.asc)</a>{stable}</p>\n'
            f'</li>\n')


def platforms(v, latest):
    """The version's files grouped by OS, in OS_GROUPS order."""
    out = '<div class="platforms">\n'
    for os_id, title in OS_GROUPS:
        files = [f for f in v["files"] if f.get("os") == os_id]
        if not files:
            continue
        out += f'<div class="platform platform-{os_id}">\n<h4>{title}</h4>\n<ul class="files">\n'
        for f in files:
            alias = latest.get(f["platform_id"])
            if alias and alias.get("version") != v["version"]:
                alias = None  # that alias serves another version
            out += file_row(f, alias)
        out += "</ul>\n</div>\n"
    return out + "</div>\n"


def verify(p, v):
    example = next((f for f in v["files"] if f.get("os") == "linux"), v["files"][0])
    sums = os.path.basename(v["checksums_url"])
    return (f'<details class="verify">\n<summary>Verify your download</summary>\n'
            f'<p>Every file is signed with the {e(p["name"])} release key, fingerprint '
            f'<code class="fpr">{fingerprint(p["key_fingerprint"])}</code>. '
            f'<a href="{e(p["key_url"])}">Download the public key</a>, then:</p>\n'
            f'<pre class="cmd"><code>gpg --import {e(os.path.basename(p["key_url"]))}\n'
            f'gpg --verify {e(example["name"])}.asc {e(example["name"])}\n'
            f'sha256sum -c --ignore-missing {e(sums)}</code></pre>\n'
            f'<p class="sums"><a href="{e(v["checksums_url"])}">{e(sums)}</a> · '
            f'<a href="{e(v["checksums_sig_url"])}">its signature</a></p>\n'
            f'</details>\n')


def previous(p):
    older = p["versions"][1:]
    if not older:
        return ""
    out = (f'<details class="previous">\n<summary>Previous versions ({len(older)})</summary>\n'
           '<ol class="versions">\n')
    for v in older:
        out += (f'<li class="version">\n<h4><a href="{e(v["url"])}">{e(v["version"])}</a> {badge(v)}'
                f'<span class="released">{day(v.get("released"))}</span></h4>\n<table>\n'
                '<thead><tr><th scope="col">File</th><th scope="col">Size</th>'
                '<th scope="col">SHA-256</th><th scope="col"><span class="visually-hidden">Signature</span></th></tr></thead>\n<tbody>\n')
        for f in v["files"]:
            out += (f'<tr><td><a href="{e(f["url"])}">{e(f["name"])}</a></td>'
                    f'<td>{size(f["size"])}</td><td><code class="sha">{e(f["sha256"])}</code></td>'
                    f'<td><a href="{e(f["sig_url"])}">.asc</a></td></tr>\n')
        out += (f'</tbody>\n</table>\n<p class="sums"><a href="{e(v["checksums_url"])}">SHA256SUMS</a> · '
                f'<a href="{e(v["checksums_sig_url"])}">.asc</a></p>\n</li>\n')
    return out + "</ol>\n</details>\n"


def product(p, products, urls, level):
    """One product's section; level is the heading level of its name (1 or 2)."""
    d, cur = display(products, p), p["versions"][0]
    name = e(p["name"]) if level == 1 else f'<a href="/{e(p["id"])}/">{e(p["name"])}</a>'
    tagline = f'<p class="tagline">{e(d["tagline"])}</p>' if d["tagline"] else ""
    pitch = f'<p class="pitch">{e(d["pitch"])}</p>\n' if d["pitch"] else ""
    return (f'<section class="product accent-{d["accent"]}" id="{e(p["id"])}" aria-labelledby="{e(p["id"])}-name">\n'
            f'<div class="product-head">{icon(d, urls)}<div>'
            f'<h{level} id="{e(p["id"])}-name" class="product-name">{name}</h{level}>{tagline}</div></div>\n'
            f'{pitch}'
            f'<h3 class="current">Version {e(cur["version"])} {badge(cur)}'
            f'<span class="released">{day(cur.get("released"))}</span></h3>\n'
            f'{platforms(cur, p.get("latest") or {})}'
            f'{verify(p, cur)}{previous(p)}</section>\n')


def page(title, description, body, urls, canonical):
    fonts = "".join(f'<link rel="preload" href="{urls[f]}" as="font" type="font/woff2" crossorigin>\n'
                    for f in ("space-grotesk-400.woff2", "space-grotesk-700.woff2"))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(canonical)}">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#07060d">
<link rel="icon" href="{urls['emblem-80.webp']}" type="image/webp">
{fonts}<link rel="stylesheet" href="{urls['kit.css']}">
</head>
<body>
<header class="site-head">
  <a class="brand" href="{HOME}"><img src="{urls['emblem-80.webp']}" width="40" height="40" alt=""> Rusty Bucket</a>
  <a class="back" href="{HOME}">← rustybucket.ai</a>
</header>
<main>
{body}</main>
<footer>
  <hr class="divider">
  <p>© 2026 Unicorn Tears Project (UTP).</p>
  <p>“Rusty Bucket”, “Rusty”, “Rusty Wave” and the logo are trademarks of UTP.</p>
</footer>
</body>
</html>
"""


INTRO = ("Every download, for every platform. Each file is signed and listed "
         "with its SHA-256, and older versions stay here.")


def render(catalog, out, products=None):
    """Write the pages and assets for a checked catalog; returns the page paths."""
    check(catalog)
    if products is None:
        with open(os.path.join(KIT, "products.json"), encoding="utf-8") as fh:
            products = json.load(fh)
    urls = write_assets(out)
    sections = "".join(product(p, products, urls, 2) for p in catalog["products"])
    body = (f'<h1 class="page-title">Software</h1>\n<p class="intro">{e(INTRO)}</p>\n{sections}')
    written = [os.path.join(out, "index.html")]
    with open(written[0], "w", encoding="utf-8") as fh:
        fh.write(page("Rusty Bucket software: downloads", INTRO, body, urls, SITE))
    for p in catalog["products"]:
        crumb = f'<p class="crumb"><a href="/">All software</a> › {e(p["name"])}</p>\n'
        d = display(products, p)
        path = os.path.join(out, p["id"], "index.html")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(page(f"{p['name']}: downloads", d["pitch"] or f"Download {p['name']}.",
                          crumb + product(p, products, urls, 1), urls, f"{SITE}{p['id']}/"))
        written.append(path)
    return written


def main(argv):
    if len(argv) != 2:
        sys.exit(__doc__)
    with open(argv[0], encoding="utf-8") as fh:
        catalog = json.load(fh)
    try:
        for path in render(catalog, argv[1]):
            print("wrote", path)
    except CatalogError as err:
        sys.exit(f"render.py: refusing the catalog: {err}")


if __name__ == "__main__":
    main(sys.argv[1:])
