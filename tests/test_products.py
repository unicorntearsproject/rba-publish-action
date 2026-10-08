"""Every product config in scripts/products/, checked generically, so adding a
product or a platform needs only its config (and its key).

Run: python3 -m unittest discover -s tests -p 'test_*.py'"""

import glob
import hashlib
import json
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts", "lib"))
sys.path.insert(0, os.path.join(ROOT, "vendor", "software-kit"))
import catalog as cat  # noqa: E402
import release_check as rc  # noqa: E402

BASE = "https://software.rustybucket.ai"
FIXTURE_FPR = "A" * 40  # stands in for a key that isn't pinned yet
CONFS = {os.path.basename(p)[:-5]: rc.load_conf(p)
         for p in sorted(glob.glob(os.path.join(ROOT, "scripts", "products", "*.json")))}
RESERVED = {"_kit", "keys", "catalog", "latest"}
with open(os.path.join(ROOT, "vendor", "software-kit", "products.json"), encoding="utf-8") as _f:
    KIT_PRODUCTS = json.load(_f)  # the vendored kit's display data


def pending(conf):
    """A config whose key isn't pinned yet (prepared ahead of the key)."""
    return not re.fullmatch(r"[0-9A-F]{40}", conf["key_fingerprint"])


def make_release(conf, d, v, fpr):
    """A consistent fake release of any product without zsync in directory d:
    one payload per platform, SHA256SUMS, the manifest, a .asc per file."""
    names = rc.expected_files(conf, v)
    vdir = f"{BASE}/{conf['product']}/{v}/"
    sums, files = [], {}
    for pid in conf["platforms"]:
        body = f"{conf['product']} {pid} {v}\n".encode() * 40
        with open(os.path.join(d, names[pid]), "wb") as f:
            f.write(body)
        digest = hashlib.sha256(body).hexdigest()
        sums.append((digest, names[pid]))
        files[pid] = {"arch": "x86_64", "name": names[pid], "url": vdir + names[pid],
                      "signature_url": vdir + names[pid] + ".asc", "size": len(body), "sha256": digest}
    with open(os.path.join(d, names[conf["checksums_file"]]), "w") as f:
        f.writelines(f"{h}  {n}\n" for h, n in sorted(sums, key=lambda x: x[1]))
    manifest = {"schema": 1, "version": v, "released": "2026-10-08", "key_fingerprint": fpr, "files": files}
    with open(os.path.join(d, conf["manifest"]), "w") as f:
        json.dump(manifest, f)
    for name in list(os.listdir(d)):
        with open(os.path.join(d, name + ".asc"), "w") as f:
            f.write("sig\n")
    return manifest


class EveryConfig(unittest.TestCase):
    def test_ids_names_and_shape(self):
        seen = {}
        for stem, conf in CONFS.items():
            with self.subTest(product=stem):
                p = conf["product"]
                self.assertEqual(p, stem, "the file name is <product>.json")
                self.assertRegex(p, r"^[a-z0-9]+(-[a-z0-9]+)*$")
                self.assertNotIn(p, RESERVED)
                self.assertEqual(conf["manifest"], f"{p}-latest.json")
                self.assertIn(conf["checksums_file"], conf["files"])
                self.assertEqual(conf["files"][conf["checksums_file"]], f"{p}-{{v}}-SHA256SUMS")
                self.assertEqual(set(conf["platforms"]), set(conf["files"]) - {conf["checksums_file"]}
                                 - {conf.get("zsync", {}).get("control")} - {None})
                self.assertTrue(set(conf.get("aliases", {})) <= set(conf["files"]))
                self.assertRegex(conf["source_repo"], r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
                for pid, meta in conf["platforms"].items():
                    self.assertIn(meta["os"], cat.OSES, pid)
                    self.assertIn(meta["kind"], cat.KINDS, pid)
                    self.assertTrue(meta["label"], pid)
                names = rc.expected_files(conf, "1.0.0-rc.1")
                for pid, name in names.items():
                    self.assertIn("1.0.0", name.replace("~", "-"), f"{pid}: the name carries the version")
                    rc.content_type(name)  # a known type
                    other = seen.setdefault(name, p)
                    self.assertEqual(other, p, f"{name} is also used by {other}")
                for need, deps in conf.get("required_with", {}).items():
                    self.assertIn(need, conf["platforms"])
                    self.assertTrue(deps and set(deps) <= set(conf["platforms"]), need)
                for alias in conf.get("aliases", {}).values():
                    self.assertIn("latest", alias)
                    self.assertNotIn("{v}", alias)

    def test_pinned_keys_are_real(self):
        for stem, conf in CONFS.items():
            if pending(conf):
                continue  # prepared ahead of its key; must not ship (see test below)
            with self.subTest(product=stem):
                key = os.path.join(ROOT, conf["key_file"])
                self.assertTrue(os.path.isfile(key), conf["key_file"])
                with open(key, "rb") as f:
                    suffix = hashlib.sha256(f.read()).hexdigest()[:8]
                self.assertTrue(conf["key_url_path"].endswith(f"-{suffix}.asc"))


@unittest.skipUnless(os.environ.get("RBA_ALLOW_PENDING_KEYS") == "1",
                     "set RBA_ALLOW_PENDING_KEYS=1 on a preparation branch")
class PendingKeysAllowed(unittest.TestCase):
    """Only runs where pending configs are expected (never in a release pin)."""

    def test_pending_configs_named(self):
        self.assertTrue(any(pending(c) for c in CONFS.values()))


class NoPendingKeyShips(unittest.TestCase):
    def test_no_config_without_a_pinned_key(self):
        if os.environ.get("RBA_ALLOW_PENDING_KEYS") == "1":
            self.skipTest("preparation branch")
        self.assertEqual([s for s, c in CONFS.items() if pending(c)], [],
                         "a product config without its real key can't be in a release pin")


class FixtureReleases(unittest.TestCase):
    """A fake release of each product without zsync passes the same checks a
    publish runs (the key fingerprint is a fixture)."""

    def test_each_product_release_checks(self):
        for stem, conf in CONFS.items():
            if conf.get("zsync"):
                continue  # Rusty Wave's zsync release has its own fixtures
            with self.subTest(product=stem), tempfile.TemporaryDirectory() as d:
                conf = dict(conf, key_fingerprint=FIXTURE_FPR)
                make_release(conf, d, "1.0.0", FIXTURE_FPR)
                files = rc.check_names(conf, d, "1.0.0")
                self.assertEqual(len(files), 2 * (len(conf["platforms"]) + 1))
                rc.check_checksums(conf, d, "1.0.0")
                rc.check_manifest(conf, d, "1.0.0", BASE, live_manifest={"version": "0.9.0"})


class RequiredWith(unittest.TestCase):
    """A file required with others (U-Stu's GPL source with its Flatpaks)
    can't be left out of the directory or the manifest."""

    def test_missing_required_file_is_refused(self):
        for stem, conf in CONFS.items():
            for need, deps in conf.get("required_with", {}).items():
                with self.subTest(product=stem, need=need), tempfile.TemporaryDirectory() as d:
                    conf2 = dict(conf, key_fingerprint=FIXTURE_FPR)
                    make_release(conf2, d, "1.0.0", FIXTURE_FPR)
                    name = rc.expected_files(conf2, "1.0.0")[need]
                    os.remove(os.path.join(d, name))
                    os.remove(os.path.join(d, name + ".asc"))
                    with self.assertRaisesRegex(rc.CheckError, f"{re.escape(name)}: required with"):
                        rc.check_names(conf2, d, "1.0.0")

    def test_missing_from_the_manifest_is_refused(self):
        for stem, conf in CONFS.items():
            for need in conf.get("required_with", {}):
                with self.subTest(product=stem, need=need), tempfile.TemporaryDirectory() as d:
                    conf2 = dict(conf, key_fingerprint=FIXTURE_FPR)
                    m = make_release(conf2, d, "1.0.0", FIXTURE_FPR)
                    del m["files"][need]
                    with open(os.path.join(d, conf2["manifest"]), "w") as f:
                        json.dump(m, f)
                    with self.assertRaisesRegex(rc.CheckError, f"files.{need}: required with"):
                        rc.check_manifest(conf2, d, "1.0.0", BASE)

    def test_not_required_when_none_of_its_files_ship(self):
        for stem, conf in CONFS.items():
            for need, deps in conf.get("required_with", {}).items():
                with self.subTest(product=stem, need=need), tempfile.TemporaryDirectory() as d:
                    plats = {k: v for k, v in conf["platforms"].items() if k not in deps and k != need}
                    if not plats:
                        continue  # every platform needs it: nothing to test
                    conf2 = dict(conf, key_fingerprint=FIXTURE_FPR, platforms=plats)
                    make_release(conf2, d, "1.0.0", FIXTURE_FPR)
                    rc.check_names(conf2, d, "1.0.0")


class TwoProducts(unittest.TestCase):
    """The catalog and the real page kit with every configured product."""

    def build(self, with_releases):
        confs = [dict(c, key_fingerprint=FIXTURE_FPR) for c in CONFS.values()]
        records, listing, alias_sha = {}, [], {}
        for conf in confs:
            p = conf["product"]
            records[p] = []
            if p not in with_releases:
                continue
            with tempfile.TemporaryDirectory() as d:
                m = make_release(dict(conf, zsync=None), d, "1.0.0", FIXTURE_FPR)
            rec = cat.release_record(conf, "1.0.0", m, "a" * 40, BASE)
            records[p].append(rec)
            for f in rec["files"]:
                listing += [{"Key": f"{p}/1.0.0/{f['name']}", "Size": f["size"]},
                            {"Key": f"{p}/1.0.0/{f['name']}.asc", "Size": 3}]
        key_urls = {c["product"]: f"{BASE}/keys/{c['product']}.asc" for c in confs}
        return cat.build_catalog(confs, records, listing, alias_sha, BASE, "2026-10-08T00:00:00Z", key_urls)

    def test_every_product_with_a_release_is_listed_and_rendered(self):
        import render
        catalog = self.build(set(CONFS))
        self.assertEqual([p["id"] for p in catalog["products"]], list(CONFS))
        with tempfile.TemporaryDirectory() as out:
            render.render(catalog, out)
            for p in CONFS:
                page = os.path.join(out, p, "index.html")
                self.assertTrue(os.path.isfile(page), p)
                with open(page, encoding="utf-8") as f:
                    html = f.read()
                for meta in CONFS[p]["platforms"].values():
                    self.assertIn(meta["label"].replace("&", "&amp;"), html)
                # Every product has the kit's display data: its name, icon and accent,
                # not the fallback tile.
                d = KIT_PRODUCTS[p]
                self.assertEqual(d["name"], CONFS[p]["display_name"])
                self.assertIn(f'class="product accent-{d["accent"]}"', html)
                self.assertIn(f'/_kit/{d["icon"]}-96.', html)
                self.assertNotIn("product-icon-blank", html)

    def test_a_product_without_releases_is_left_out(self):
        first = next(iter(CONFS))
        catalog = self.build({first})
        self.assertEqual([p["id"] for p in catalog["products"]], [first])


if __name__ == "__main__":
    unittest.main()
