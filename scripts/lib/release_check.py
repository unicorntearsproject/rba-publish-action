#!/usr/bin/env python3
"""Offline checks and generators for publish-release.sh (docs/publishing.md).

No AWS calls and no network here: everything the shell script feeds in is a
local file, so every check is unit-testable (tests/test_release_check.py).
Standard library only.
"""

import argparse
import base64
import hashlib
import html
import json
import os
import re
import sys
import zipfile

# SemVer 2.0 with an optional pre-release; no build metadata (nothing needs
# it, and it would end up in paths). Numeric identifiers have no leading
# zeros; pre-release identifiers are dot-separated [0-9A-Za-z-]+.
_NUM = r"(?:0|[1-9]\d*)"
_PRE_ID = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
SEMVER = re.compile(rf"^({_NUM})\.({_NUM})\.({_NUM})(?:-({_PRE_ID}(?:\.{_PRE_ID})*))?$")

CONTENT_TYPES = [
    # Binaries use types CloudFront never compresses, so Range requests
    # (zsync) get exact bytes.
    (".AppImage.zsync", "application/x-zsync"),
    (".AppImage", "application/octet-stream"),
    (".deb", "application/vnd.debian.binary-package"),
    (".rpm", "application/x-rpm"),
    (".tar.gz", "application/gzip"),
    (".flatpak", "application/vnd.flatpak"),
    (".exe", "application/vnd.microsoft.portable-executable"),
    (".zip", "application/zip"),
    (".dmg", "application/x-apple-diskimage"),
    (".asc", "application/pgp-signature"),
    (".json", "application/json"),
    (".html", "text/html; charset=utf-8"),
    ("SHA256SUMS", "text/plain; charset=utf-8"),
]


class CheckError(Exception):
    pass


def load_conf(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def normalize_version(raw):
    v = raw[1:] if raw.startswith("v") else raw
    if not SEMVER.match(v):
        raise CheckError(f"version {raw!r} is not SemVer x.y.z[-prerelease] (no build metadata)")
    return v


def semver_key(v):
    m = SEMVER.match(v)
    if not m:
        raise CheckError(f"not semver: {v!r}")
    major, minor, patch, pre = m.groups()
    # A release sorts after its pre-releases; pre-release fields compare
    # numerically when numeric (SemVer 2.0.0, section 11).
    pre_key = (1,) if pre is None else (0,) + tuple(
        (0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split(".")
    )
    return (int(major), int(minor), int(patch), pre_key)


def semver_gt(a, b):
    return semver_key(a) > semver_key(b)


def version_forms(v):
    """The version as each packaging format spells it:
    {v}      SemVer, as tagged:            1.0.0-rc1     1.0.0
    {deb_v}  Debian (~ sorts before):      1.0.0~rc1     1.0.0
    {rpm_vr} RPM version-release (Fedora   1.0.0-0.1.rc1 1.0.0-1
             pre-release convention)."""
    m = SEMVER.match(v)
    if not m:
        raise CheckError(f"not SemVer: {v!r}")
    core, pre = v.split("-", 1)[0], m.group(4)
    if pre is None:
        return {"v": v, "deb_v": v, "rpm_vr": f"{core}-1"}
    if "-" in pre:
        # RPM forbids '-' in Release, and Debian's would read as a revision.
        raise CheckError(f"pre-release {pre!r} has a '-', which deb and rpm versions can't carry")
    return {"v": v, "deb_v": f"{core}~{pre}", "rpm_vr": f"{core}-0.1.{pre}"}


def expected_files(conf, v):
    """Platform id -> exact file name for version v."""
    forms = version_forms(v)

    def expand(tmpl):
        return re.sub(r"\{(\w+)\}", lambda m: forms[m.group(1)], tmpl)

    try:
        return {pid: expand(tmpl) for pid, tmpl in conf["files"].items()}
    except KeyError as e:
        raise CheckError(f"unknown placeholder {{{e.args[0]}}} in the file list")


def content_type(name):
    for suffix, ctype in CONTENT_TYPES:
        if name.endswith(suffix):
            return ctype
    raise CheckError(f"no content type for {name!r}")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_names(conf, release_dir, v):
    """Every file is on the list, its .asc, or the manifest pair; every
    release file has its .asc; the checksums file is present. Returns the
    sorted list of versioned files to upload (release files and their .asc)."""
    allowed = set(expected_files(conf, v).values())
    manifest = conf["manifest"]
    present = set(os.listdir(release_dir))
    problems = []
    for name in sorted(present):
        path = os.path.join(release_dir, name)
        if not os.path.isfile(path) or os.path.islink(path):
            problems.append(f"{name}: not a regular file")
            continue
        base = name[:-4] if name.endswith(".asc") else name
        if base not in allowed and base != manifest:
            problems.append(f"{name}: not on the {conf['product']} {v} file list")
    for name in sorted(present):
        if not name.endswith(".asc") and f"{name}.asc" not in present:
            problems.append(f"{name}: missing {name}.asc")
    checksums = expected_files(conf, v)[conf["checksums_file"]]
    for required in (checksums, manifest):
        if required not in present:
            problems.append(f"{required}: missing")
    zs = conf.get("zsync")
    if zs:
        names = expected_files(conf, v)
        if (names[zs["target"]] in present) != (names[zs["control"]] in present):
            problems.append(f"{names[zs['target']]} and {names[zs['control']]} must be published together")
    # required_with: {"<pid>": ["<pid>", ...]}: if any of those ships, <pid>
    # must ship too (e.g. GPL corresponding source with bundled binaries).
    names = expected_files(conf, v)
    for need, deps in conf.get("required_with", {}).items():
        shipped = [names[d] for d in deps if names[d] in present]
        if shipped and names[need] not in present:
            problems.append(f"{names[need]}: required with {', '.join(shipped)}")
    if problems:
        raise CheckError("file names:\n  " + "\n  ".join(problems))
    return sorted(n for n in present if n not in (manifest, manifest + ".asc"))


def parse_sha256sums(path):
    sums = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            m = re.match(r"^([0-9a-f]{64}) [ *](.+)$", line)
            if not m:
                raise CheckError(f"{os.path.basename(path)}: bad line {line!r}")
            sums[m.group(2)] = m.group(1)
    return sums


def check_checksums(conf, release_dir, v):
    """Every entry matches its file, and every release file except the
    checksums file itself and signatures is listed."""
    names = expected_files(conf, v)
    sums_name = names[conf["checksums_file"]]
    sums = parse_sha256sums(os.path.join(release_dir, sums_name))
    problems = []
    for name, digest in sorted(sums.items()):
        path = os.path.join(release_dir, name)
        if not os.path.isfile(path):
            problems.append(f"{sums_name} lists {name}, which is missing")
        elif sha256_file(path) != digest:
            problems.append(f"{name}: SHA-256 differs from {sums_name}")
    for name in sorted(os.listdir(release_dir)):
        if name.endswith(".asc") or name in (sums_name, conf["manifest"]):
            continue
        if name not in sums:
            problems.append(f"{name}: not listed in {sums_name}")
    if problems:
        raise CheckError("checksums:\n  " + "\n  ".join(problems))


def parse_zsync_header(path):
    header = {}
    with open(path, "rb") as f:
        for raw in f:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line == "":
                break
            key, _, value = line.partition(": ")
            header[key] = value
    return header


def check_manifest(conf, release_dir, v, base_url, live_manifest=None):
    """RW's signed manifest, checked against the local files (the bucket is
    checked separately after upload). Returns the parsed manifest."""
    product = conf["product"]
    with open(os.path.join(release_dir, conf["manifest"]), encoding="utf-8") as f:
        m = json.load(f)
    names = expected_files(conf, v)
    allowed = set(names.values())
    vdir = f"{base_url}/{product}/{v}/"
    latest = f"{base_url}/{product}/latest/"
    problems = []
    if m.get("schema") != 1:
        problems.append(f"schema is {m.get('schema')!r}, expected 1")
    if m.get("version") != v:
        problems.append(f"version is {m.get('version')!r}, expected {v!r}")
    if m.get("key_fingerprint") != conf["key_fingerprint"]:
        problems.append(f"key_fingerprint is {m.get('key_fingerprint')!r}")
    files = m.get("files")
    if not isinstance(files, dict) or not files:
        problems.append("files is empty or not an object")
        files = {}
    zs = conf.get("zsync", {})
    for pid, entry in sorted(files.items()):
        name = entry.get("name")
        if pid not in names or names[pid] != name:
            problems.append(f"files.{pid}: name {name!r} doesn't match the list ({names.get(pid)!r})")
            continue
        if entry.get("url") != vdir + name:
            problems.append(f"files.{pid}.url is {entry.get('url')!r}, expected {vdir + name!r}")
        if entry.get("signature_url") != vdir + name + ".asc":
            problems.append(f"files.{pid}.signature_url is {entry.get('signature_url')!r}")
        path = os.path.join(release_dir, name)
        if not os.path.isfile(path):
            problems.append(f"files.{pid}: {name} is not in the release directory")
            continue
        if entry.get("size") != os.path.getsize(path):
            problems.append(f"files.{pid}.size {entry.get('size')} != {os.path.getsize(path)}")
        if entry.get("sha256") != sha256_file(path):
            problems.append(f"files.{pid}.sha256 doesn't match {name}")
        if "zsync_url" in entry:
            want = latest + conf["aliases"].get(zs.get("control"), "")
            if pid != zs.get("target") or entry["zsync_url"] != want:
                problems.append(f"files.{pid}.zsync_url is {entry['zsync_url']!r}, expected {want!r}")
    # The zsync control file must point at the versioned target, by size.
    if zs and names[zs["control"]] in os.listdir(release_dir):
        target = names[zs["target"]]
        header = parse_zsync_header(os.path.join(release_dir, names[zs["control"]]))
        if header.get("URL") != vdir + target:
            problems.append(f"{names[zs['control']]}: URL is {header.get('URL')!r}, expected {vdir + target!r}")
        tpath = os.path.join(release_dir, target)
        if os.path.isfile(tpath) and header.get("Length") != str(os.path.getsize(tpath)):
            problems.append(f"{names[zs['control']]}: Length {header.get('Length')!r} != {os.path.getsize(tpath)}")
    if live_manifest is not None:
        live_v = live_manifest.get("version", "")
        if not SEMVER.match(live_v) or not semver_gt(v, live_v):
            problems.append(f"version {v} is not newer than the live {live_v!r}")
    for need, deps in conf.get("required_with", {}).items():
        if any(d in files for d in deps) and need not in files:
            problems.append(f"files.{need}: required with {', '.join(d for d in deps if d in files)}")
    unknown = set(f["name"] for f in files.values() if isinstance(f, dict)) - allowed
    if unknown:
        problems.append(f"unknown names: {sorted(unknown)}")
    if problems:
        raise CheckError("manifest:\n  " + "\n  ".join(problems))
    return m


def release_commits(conf, release_dir, v):
    """The commits the release names, as [(source, sha)]: the manifest's
    `commit` field and build-info.json inside the configured file, if any.
    publish-release.sh requires each to equal the tag's commit."""
    found = []
    with open(os.path.join(release_dir, conf["manifest"]), encoding="utf-8") as f:
        m = json.load(f)
    if "commit" in m:
        found.append((conf["manifest"], m["commit"]))
    bi = conf.get("build_info")
    if bi:
        name = expected_files(conf, v)[bi["file"]]
        path = os.path.join(release_dir, name)
        if os.path.isfile(path):
            try:
                with zipfile.ZipFile(path) as z:
                    info = json.loads(z.read(bi["path"])) if bi["path"] in z.namelist() else None
            except (zipfile.BadZipFile, json.JSONDecodeError) as e:
                raise CheckError(f"{name}: can't read {bi['path']}: {e}")
            if info is not None:
                if "version" in info and info["version"] != v:
                    raise CheckError(f"{name}:{bi['path']} says version {info['version']!r}, not {v!r}")
                if "commit" in info:
                    found.append((f"{name}:{bi['path']}", info["commit"]))
    for source, sha in found:
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise CheckError(f"{source}: commit {sha!r} is not a full SHA-1")
    return found


def hex_to_b64(hexdigest):
    return base64.b64encode(bytes.fromhex(hexdigest)).decode()


def parse_ranges(spec):
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out.append((int(a), int(b)))
    return out


def check_range_response(local_path, header_text, body, ranges):
    """A Range response must be 206 with exactly the requested bytes: one
    part with Content-Range, or multipart/byteranges with one part per range.
    Returns a description; raises CheckError otherwise (e.g. 200 + whole)."""
    blocks = [b for b in re.split(r"\r?\n\r?\n", header_text.strip()) if b.startswith("HTTP/")]
    if not blocks:
        raise CheckError("no HTTP status line in the headers")
    lines = re.split(r"\r?\n", blocks[-1])
    status = lines[0].split()[1]
    headers = {}
    for line in lines[1:]:
        k, _, v = line.partition(":")
        headers[k.strip().lower()] = v.strip()
    with open(local_path, "rb") as f:
        data = f.read()
    if status != "206":
        whole = " (the whole object)" if body == data else ""
        raise CheckError(f"HTTP {status}{whole}, expected 206")
    if len(ranges) == 1:
        a, b = ranges[0]
        if headers.get("content-range", "").split("/")[0] != f"bytes {a}-{b}":
            raise CheckError(f"Content-Range is {headers.get('content-range')!r}")
        if body != data[a:b + 1]:
            raise CheckError("range bytes differ from the local file")
        return "206, bytes match"
    ctype = headers.get("content-type", "")
    m = re.match(r"multipart/byteranges;\s*boundary=\"?([^\";]+)\"?", ctype)
    if not m:
        raise CheckError(f"Content-Type is {ctype!r}, expected multipart/byteranges")
    parts = body.split(b"--" + m.group(1).encode())[1:-1]
    if len(parts) != len(ranges):
        raise CheckError(f"{len(parts)} parts for {len(ranges)} ranges")
    for (a, b), part in zip(ranges, parts):
        head, _, payload = part.lstrip(b"\r\n").partition(b"\r\n\r\n")
        if f"bytes {a}-{b}/".encode() not in head:
            raise CheckError(f"part for {a}-{b} has headers {head!r}")
        if payload[:-2] != data[a:b + 1]:
            raise CheckError(f"part {a}-{b} bytes differ from the local file")
    return f"206 multipart, {len(ranges)} parts, bytes match"


_INLINE_STYLE = """<style>
:root{--bg:#0b0d12;--fg:#e8e6e3;--muted:#9aa3ad;--accent:#ff6b2c;--line:#232833}
body{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:960px;margin:0 auto}
h1{font-size:1.4rem;color:var(--accent)}
a{color:var(--accent)}
table{width:100%;border-collapse:collapse;font-family:ui-monospace,monospace;font-size:13px}
td{padding:6px 8px;border-bottom:1px solid var(--line);word-break:break-all}
td.n{text-align:right;white-space:nowrap;color:var(--muted)}
p,code{color:var(--muted)}
</style>"""


def render_index(title, rows, key_fpr=None, parent=True, stylesheet=None):
    """A plain listing page: rows are (href, label, size or None, date).
    With a stylesheet (the page kit's fingerprinted CSS) it links that and
    has no inline style, so a CSP with style-src 'self' allows it."""
    esc = html.escape
    body = []
    for href, label, size, date in rows:
        size_s = "" if size is None else f"{size:,}"
        body.append(
            f'<tr><td><a href="{esc(href, quote=True)}">{esc(label)}</a></td>'
            f"<td class=n>{size_s}</td><td>{esc(date)}</td></tr>"
        )
    up = '<p><a href="../">↑ Parent directory</a></p>' if parent else ""
    key = (
        f"<p>Releases are signed with key <code>{esc(fmt_fpr(key_fpr))}</code>. "
        "Check each file against its <code>.asc</code> and the SHA256SUMS.</p>"
        if key_fpr else ""
    )
    style = (f'<link rel="stylesheet" href="{esc(stylesheet, quote=True)}">' if stylesheet
             else _INLINE_STYLE)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
{style}
</head>
<body>
<main>
<h1>{esc(title)}</h1>
{key}
{up}
<table>
{chr(10).join(body)}
</table>
</main>
</body>
</html>
"""


def fmt_fpr(fpr):
    return " ".join(fpr[i:i + 4] for i in range(0, len(fpr), 4))


def build_indexes(listing, products, key_fprs, stylesheet=None, folders_only=False):
    """listing: [{"Key","Size","LastModified"}] for the whole bucket.
    Returns {key: html} for the root, each product and each folder under it
    (versions and latest/). folders_only: just the folder pages (the page kit
    renders the root and product pages)."""
    by_dir = {}
    for obj in listing:
        key = obj["Key"]
        if key.endswith("index.html"):
            continue
        d, _, name = key.rpartition("/")
        by_dir.setdefault(d, []).append((name, obj["Size"], obj["LastModified"][:10]))
    out = {}
    root_rows = [(f"{p}/", f"{p}/", None, "") for p in sorted(products)]
    if not folders_only:
        out["index.html"] = render_index("software.rustybucket.ai", root_rows, parent=False, stylesheet=stylesheet)
    for p in sorted(products):
        subdirs = {d.split("/")[1] for d in by_dir if d.startswith(p + "/") and d.count("/") == 1}
        versions = sorted((s for s in subdirs if SEMVER.match(s)), key=semver_key, reverse=True)
        ordered = (["latest"] if "latest" in subdirs else []) + versions
        rows = [(f"{s}/", f"{s}/", None, "") for s in ordered]
        if not folders_only:
            out[f"{p}/index.html"] = render_index(products[p], rows, key_fprs.get(p), stylesheet=stylesheet)
        for s in ordered:
            files = sorted(by_dir.get(f"{p}/{s}", []))
            rows = [(n, n, size, date) for n, size, date in files]
            out[f"{p}/{s}/index.html"] = render_index(f"{products[p]} {s}", rows, key_fprs.get(p),
                                                       stylesheet=stylesheet)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("version"); s.add_argument("raw")
    s = sub.add_parser("gt"); s.add_argument("a"); s.add_argument("b")
    s = sub.add_parser("content-type"); s.add_argument("name")
    for name in ("names", "checksums", "manifest"):
        s = sub.add_parser(name)
        s.add_argument("--conf", required=True)
        s.add_argument("--dir", required=True)
        s.add_argument("--version", required=True)
        if name == "manifest":
            s.add_argument("--base-url", required=True)
            s.add_argument("--live", help="the live manifest file, if any")
    s = sub.add_parser("manifest-files", help="print name<TAB>size<TAB>sha256 per manifest file")
    s.add_argument("--manifest", required=True)
    s = sub.add_parser("commits", help="print source<TAB>commit for each commit the release names")
    s.add_argument("--conf", required=True)
    s.add_argument("--dir", required=True)
    s.add_argument("--version", required=True)
    s = sub.add_parser("name", help="print the exact file name of one platform id")
    s.add_argument("--conf", required=True)
    s.add_argument("--version", required=True)
    s.add_argument("--id", required=True)
    s = sub.add_parser("hex2b64"); s.add_argument("hex")
    s = sub.add_parser("ranges", help="check a Range response against the local file")
    s.add_argument("--file", required=True)
    s.add_argument("--headers", required=True, help="curl -D output")
    s.add_argument("--body", required=True)
    s.add_argument("--ranges", required=True, help="e.g. 0-1023,4096-8191")
    s = sub.add_parser("indexes")
    s.add_argument("--listing", required=True, help="list-objects-v2 JSON (Contents)")
    s.add_argument("--confs", nargs="+", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--stylesheet", help="link this stylesheet instead of the inline style")
    s.add_argument("--folders-only", action="store_true", help="only version and latest/ folder pages")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "version":
            print(normalize_version(args.raw))
        elif args.cmd == "gt":
            return 0 if semver_gt(args.a, args.b) else 1
        elif args.cmd == "content-type":
            print(content_type(args.name))
        elif args.cmd == "names":
            print("\n".join(check_names(load_conf(args.conf), args.dir, args.version)))
        elif args.cmd == "checksums":
            check_checksums(load_conf(args.conf), args.dir, args.version)
        elif args.cmd == "manifest":
            live = None
            if args.live:
                with open(args.live, encoding="utf-8") as f:
                    live = json.load(f)
            check_manifest(load_conf(args.conf), args.dir, args.version, args.base_url, live)
        elif args.cmd == "manifest-files":
            with open(args.manifest, encoding="utf-8") as f:
                m = json.load(f)
            for entry in m["files"].values():
                print(f"{entry['name']}\t{entry['size']}\t{entry['sha256']}")
        elif args.cmd == "commits":
            for source, sha in release_commits(load_conf(args.conf), args.dir, args.version):
                print(f"{source}\t{sha}")
        elif args.cmd == "name":
            names = expected_files(load_conf(args.conf), args.version)
            if args.id not in names:
                raise CheckError(f"no platform id {args.id!r}")
            print(names[args.id])
        elif args.cmd == "hex2b64":
            print(hex_to_b64(args.hex))
        elif args.cmd == "ranges":
            with open(args.headers, encoding="latin-1") as f:
                header_text = f.read()
            with open(args.body, "rb") as f:
                body = f.read()
            print(check_range_response(args.file, header_text, body, parse_ranges(args.ranges)))
        elif args.cmd == "indexes":
            with open(args.listing, encoding="utf-8") as f:
                listing = json.load(f) or []
            confs = [load_conf(c) for c in args.confs]
            pages = build_indexes(
                listing,
                {c["product"]: c["display_name"] for c in confs},
                {c["product"]: c["key_fingerprint"] for c in confs},
                stylesheet=args.stylesheet,
                folders_only=args.folders_only,
            )
            for key, page in pages.items():
                path = os.path.join(args.out, key)
                os.makedirs(os.path.dirname(path) or args.out, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(page)
                print(key)
    except CheckError as e:
        print(f"release_check: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
