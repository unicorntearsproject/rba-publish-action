"""catalog.json (schema 1) for software.rustybucket.ai.

Two steps, both offline and unit-tested (tests/test_catalog.py):

- release_record(): after a verified publish, the immutable per-version
  record <product>/<version>/release.json, from the publisher's checked
  manifest, the tag gate's commit and the product config.
- build_catalog(): every product's records, cross-checked against the
  bucket listing (each file present, same size), plus the latest/ aliases,
  each matched by SHA-256 to the version it serves.

Anything inconsistent raises CatalogError; nothing is silently dropped.
Schema: docs/catalog.md.
"""

import argparse
import json
import os
import re
import sys

import release_check as rc

SCHEMA = 1
KINDS = {"installer", "portable", "package", "web"}
OSES = {"linux", "windows", "macos", "any"}


class CatalogError(Exception):
    pass


def _platforms(conf):
    """platform_id -> display metadata, in config order; only these are
    downloadable files (SHA256SUMS, .zsync and .asc aren't)."""
    plats = conf.get("platforms")
    if not plats:
        raise CatalogError(f"{conf['product']}: no platforms in the product config")
    for pid, meta in plats.items():
        if pid not in conf["files"]:
            raise CatalogError(f"{conf['product']}: platform {pid} has no file template")
        if meta.get("os") not in OSES or meta.get("kind") not in KINDS or not meta.get("label"):
            raise CatalogError(f"{conf['product']}: platform {pid} needs os, kind and label")
    return plats


def release_record(conf, v, manifest, tag_commit, base_url):
    """The release record for version v. The manifest must already have
    passed release_check.check_manifest and the bucket check."""
    if manifest.get("version") != v:
        raise CatalogError(f"manifest is {manifest.get('version')!r}, not {v!r}")
    if not re.fullmatch(r"[0-9a-f]{40}", tag_commit or ""):
        raise CatalogError(f"tag commit {tag_commit!r} is not a full SHA-1")
    product = conf["product"]
    names = rc.expected_files(conf, v)
    vdir = f"{base_url}/{product}/{v}/"
    files = []
    for pid, meta in _platforms(conf).items():
        entry = manifest["files"].get(pid)
        if entry is None:
            continue  # this release doesn't ship that platform
        f = {
            "platform_id": pid,
            "os": meta["os"],
            "arch": entry["arch"],
            "kind": meta["kind"],
            "label": meta["label"],
            "name": names[pid],
            "url": vdir + names[pid],
            "size": entry["size"],
            "sha256": entry["sha256"],
            "sig_url": vdir + names[pid] + ".asc",
        }
        if "zsync_url" in entry:
            f["zsync_url"] = entry["zsync_url"]
        if "note" in entry:
            f["note"] = entry["note"]
        files.append(f)
    if not files:
        raise CatalogError(f"{product} {v}: no downloadable files")
    sums = names[conf["checksums_file"]]
    return {
        "schema": SCHEMA,
        "product": product,
        "version": v,
        "prerelease": "-" in v,
        "tag": f"v{v}",
        "commit": tag_commit,
        "released": manifest["released"],
        "url": vdir,
        "checksums_url": vdir + sums,
        "checksums_sig_url": vdir + sums + ".asc",
        "files": files,
    }


def build_catalog(confs, records, listing, alias_sha256, base_url, generated, key_urls=None):
    """confs: product configs in display order. records: {product: [record]}.
    listing: list-objects-v2 Contents ({Key, Size}) for the whole bucket.
    alias_sha256: {key: hex} for every object under <product>/latest/ that
    is an alias (from head-object checksums). key_urls: {product: url}."""
    sizes = {o["Key"]: o["Size"] for o in listing}
    out = {"schema": SCHEMA, "generated": generated, "base_url": base_url, "products": []}
    for conf in confs:
        product = conf["product"]
        plats = _platforms(conf)
        recs = records.get(product, [])
        by_version = {}
        for r in recs:
            if r.get("schema") != SCHEMA or r.get("product") != product:
                raise CatalogError(f"{product}: record {r.get('version')!r} has schema/product {r.get('schema')!r}/{r.get('product')!r}")
            if r["version"] in by_version:
                raise CatalogError(f"{product}: two records for {r['version']}")
            by_version[r["version"]] = r
            for f in r["files"]:
                key = f"{product}/{r['version']}/{f['name']}"
                if key not in sizes:
                    raise CatalogError(f"{key}: in the release record but not in the bucket")
                if sizes[key] != f["size"]:
                    raise CatalogError(f"{key}: {sizes[key]} bytes in the bucket, {f['size']} in the record")
                if f"{key}.asc" not in sizes:
                    raise CatalogError(f"{key}.asc: missing from the bucket")
        # Every version folder in the bucket must have a record.
        folders = {k.split("/")[1] for k in sizes if k.startswith(product + "/") and k.count("/") >= 2}
        missing = sorted(f for f in folders if rc.SEMVER.match(f) and f not in by_version)
        if missing:
            raise CatalogError(f"{product}: no release record for {', '.join(missing)}")
        if not by_version:
            continue  # nothing published yet: the product isn't listed
        versions = sorted(by_version.values(), key=lambda r: rc.semver_key(r["version"]), reverse=True)
        latest = {}
        for pid, alias in conf.get("aliases", {}).items():
            if pid not in plats:
                continue  # the .zsync alias is reached through zsync_url
            key = f"{product}/latest/{alias}"
            if key not in sizes:
                continue  # not published yet
            sha = alias_sha256.get(key)
            if sha is None:
                raise CatalogError(f"{key}: no SHA-256 for the alias")
            serves = [r["version"] for r in versions
                      for f in r["files"] if f["platform_id"] == pid and f["sha256"] == sha]
            if not serves:
                raise CatalogError(f"{key}: matches no published version")
            latest[pid] = {
                "name": alias,
                "url": f"{base_url}/{key}",
                "sig_url": f"{base_url}/{key}.asc",
                "version": serves[0],
            }
        out["products"].append({
            "id": product,
            "name": conf["display_name"],
            "key_fingerprint": conf["key_fingerprint"],
            "key_url": (key_urls or {}).get(product),
            "manifest_url": f"{base_url}/{product}/latest/{conf['manifest']}",
            "latest_version": versions[0]["version"],
            "latest": latest,
            "versions": [{k: v for k, v in r.items() if k not in ("schema", "product")} for r in versions],
        })
    return out


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    ap = argparse.ArgumentParser(description="catalog.json tools (schema 1)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("record", help="print the release record for a verified publish")
    s.add_argument("--conf", required=True)
    s.add_argument("--version", required=True)
    s.add_argument("--manifest", required=True)
    s.add_argument("--commit", required=True)
    s.add_argument("--base-url", required=True)
    s = sub.add_parser("build", help="print catalog.json")
    s.add_argument("--confs", nargs="+", required=True)
    s.add_argument("--listing", required=True, help="list-objects-v2 Contents JSON")
    s.add_argument("--alias-sha", required=True, help='JSON {"<key>": "<sha256 hex>"} for the latest/ aliases')
    s.add_argument("--records", required=True, help="directory of <product>/<version>.json records")
    s.add_argument("--base-url", required=True)
    s.add_argument("--generated", required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "record":
            conf = rc.load_conf(args.conf)
            rec = release_record(conf, args.version, _load(args.manifest), args.commit, args.base_url)
            print(json.dumps(rec, indent=2))
        elif args.cmd == "build":
            confs = [rc.load_conf(c) for c in args.confs]
            records, key_urls = {}, {}
            for conf in confs:
                p = conf["product"]
                d = os.path.join(args.records, p)
                records[p] = [_load(os.path.join(d, n)) for n in sorted(os.listdir(d))] if os.path.isdir(d) else []
                if conf.get("key_url_path"):
                    key_urls[p] = f"{args.base_url}/{conf['key_url_path']}"
            listing = _load(args.listing) or []
            print(json.dumps(build_catalog(confs, records, listing, _load(args.alias_sha),
                                           args.base_url, args.generated, key_urls), indent=2))
    except (CatalogError, rc.CheckError, KeyError) as e:
        print(f"catalog: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
