"""Offline tests for scripts/lib/catalog.py (run: python3 -m unittest discover -s tests)."""

import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
sys.path.insert(0, os.path.dirname(__file__))
import catalog as cat  # noqa: E402
import release_check as rc  # noqa: E402
import test_release_check as fixtures  # noqa: E402

BASE = "https://software.rustybucket.ai"
SHA_A = "d5f5935dc3a28d249baeae6236b345dc3b07f3b5"
SHA_B = "6e2566503ca56bf8c2393553a3ddbaa1195d8cc4"

# The platform display data this module expects in the product config.
PLATFORMS = {
    "linux-appimage": {"os": "linux", "kind": "portable", "label": "AppImage"},
    "linux-deb": {"os": "linux", "kind": "package", "label": "Debian/Ubuntu (.deb)"},
    "linux-rpm": {"os": "linux", "kind": "package", "label": "Fedora/RHEL (.rpm)"},
    "linux-flatpak": {"os": "linux", "kind": "package", "label": "Flatpak"},
    "linux-tarball": {"os": "linux", "kind": "portable", "label": "Linux tarball (.tar.gz)"},
    "windows-installer": {"os": "windows", "kind": "installer", "label": "Windows installer (.exe)"},
    "windows-portable": {"os": "windows", "kind": "portable", "label": "Windows portable (.zip)"},
    "macos-dmg": {"os": "macos", "kind": "installer", "label": "macOS (.dmg)"},
    "web-pwa": {"os": "any", "kind": "web", "label": "Web app (.zip)"},
}
CONF = copy.deepcopy(fixtures.CONF)
CONF["platforms"] = PLATFORMS
CONF["aliases"] = {
    "linux-appimage": "rusty-wave-latest-x86_64.AppImage",
    "linux-appimage-zsync": "rusty-wave-latest-x86_64.AppImage.zsync",
    "linux-deb": "rusty-wave-latest_amd64.deb",
    "macos-dmg": "rusty-wave-latest-macos-universal.dmg",
}


def published(v, skip=()):
    """A release as the bucket would hold it: the manifest, a record and the
    bucket listing entries (versioned files and their .asc)."""
    with tempfile.TemporaryDirectory() as d:
        m = fixtures.make_release(d, v=v, skip=skip)
        sizes = {n: os.path.getsize(os.path.join(d, n)) for n in os.listdir(d)}
    m["released"] = "2026-10-07"
    if "macos-dmg" in m["files"]:
        m["files"]["macos-dmg"]["note"] = "beta: ad-hoc signed only"
    record = cat.release_record(CONF, v, m, SHA_A if v != "0.0.5" else SHA_B, BASE)
    listing = [{"Key": f"rusty-wave/{v}/{n}", "Size": s} for n, s in sizes.items()
               if n not in (CONF["manifest"], CONF["manifest"] + ".asc")]
    listing.append({"Key": f"rusty-wave/{v}/release.json", "Size": 1})
    return m, record, listing


def alias_listing(entries):
    """[(alias name, sha256)] -> listing rows and the alias SHA map."""
    rows, shas = [], {}
    for name, sha in entries:
        key = f"rusty-wave/latest/{name}"
        rows += [{"Key": key, "Size": 1}, {"Key": key + ".asc", "Size": 1}]
        shas[key] = sha
    return rows, shas


class RecordTests(unittest.TestCase):
    def test_record_fields(self):
        m, r, _ = published("1.0.0-rc1")
        self.assertEqual((r["schema"], r["version"], r["prerelease"], r["tag"], r["commit"], r["released"]),
                         (1, "1.0.0-rc1", True, "v1.0.0-rc1", SHA_A, "2026-10-07"))
        self.assertEqual(r["checksums_url"], f"{BASE}/rusty-wave/1.0.0-rc1/rusty-wave-1.0.0-rc1-SHA256SUMS")
        pids = [f["platform_id"] for f in r["files"]]
        self.assertEqual(pids, list(PLATFORMS))  # config order; no SHA256SUMS or .zsync entries
        deb = r["files"][1]
        self.assertEqual(deb["name"], "rusty-wave_1.0.0~rc1_amd64.deb")
        self.assertEqual(deb["url"], f"{BASE}/rusty-wave/1.0.0-rc1/rusty-wave_1.0.0~rc1_amd64.deb")
        self.assertEqual(deb["sig_url"], deb["url"] + ".asc")
        self.assertEqual((deb["os"], deb["kind"], deb["arch"]), ("linux", "package", "x86_64"))
        self.assertEqual(deb["sha256"], m["files"]["linux-deb"]["sha256"])
        appimage = r["files"][0]
        self.assertTrue(appimage["zsync_url"].endswith("/latest/rusty-wave-latest-x86_64.AppImage.zsync"))
        self.assertNotIn("zsync_url", deb)
        self.assertEqual(r["files"][7]["note"], "beta: ad-hoc signed only")

    def test_final_is_not_prerelease(self):
        self.assertFalse(published("1.0.0")[1]["prerelease"])

    def test_missing_platform_is_simply_absent(self):
        _, r, _ = published("1.0.0", skip=("macos-dmg",))
        self.assertNotIn("macos-dmg", [f["platform_id"] for f in r["files"]])

    def test_rejects_bad_inputs(self):
        m, _, _ = published("1.0.0")
        with self.assertRaisesRegex(cat.CatalogError, "not '1.0.1'"):
            cat.release_record(CONF, "1.0.1", m, SHA_A, BASE)
        with self.assertRaisesRegex(cat.CatalogError, "full SHA-1"):
            cat.release_record(CONF, "1.0.0", m, "d5f5935", BASE)
        bad = copy.deepcopy(CONF)
        bad["platforms"]["linux-deb"] = {"os": "linux", "kind": "binary", "label": "x"}
        with self.assertRaisesRegex(cat.CatalogError, "needs os, kind and label"):
            cat.release_record(bad, "1.0.0", m, SHA_A, BASE)

    def test_record_is_json(self):
        json.dumps(published("1.0.0-rc1")[1])


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.m5, self.r5, self.l5 = published("0.0.5")
        self.m1, self.r1, self.l1 = published("1.0.0-rc1", skip=("macos-dmg",))
        rows, self.shas = alias_listing([
            ("rusty-wave-latest-x86_64.AppImage", self.m1["files"]["linux-appimage"]["sha256"]),
            ("rusty-wave-latest-x86_64.AppImage.zsync", "0" * 64),
            ("rusty-wave-latest_amd64.deb", self.m1["files"]["linux-deb"]["sha256"]),
            ("rusty-wave-latest-macos-universal.dmg", self.m5["files"]["macos-dmg"]["sha256"]),
        ])
        self.listing = self.l5 + self.l1 + rows

    def build(self, records=None, listing=None, shas=None):
        return cat.build_catalog([CONF], {"rusty-wave": records or [self.r5, self.r1]},
                                 listing or self.listing, shas or self.shas, BASE, "2026-10-07T12:00:00Z",
                                 {"rusty-wave": f"{BASE}/keys/rusty-wave-release-E13FF843.asc"})

    def test_shape_and_order(self):
        c = self.build()
        self.assertEqual((c["schema"], c["base_url"], c["generated"]), (1, BASE, "2026-10-07T12:00:00Z"))
        p = c["products"][0]
        self.assertEqual((p["id"], p["name"], p["latest_version"]), ("rusty-wave", "Rusty Wave", "1.0.0-rc1"))
        self.assertEqual([v["version"] for v in p["versions"]], ["1.0.0-rc1", "0.0.5"])
        self.assertEqual(p["key_url"], f"{BASE}/keys/rusty-wave-release-E13FF843.asc")
        self.assertEqual(p["manifest_url"], f"{BASE}/rusty-wave/latest/rusty-wave-latest.json")
        self.assertNotIn("schema", p["versions"][0])
        self.assertNotIn("product", p["versions"][0])
        json.dumps(c)

    def test_latest_aliases_report_the_version_they_serve(self):
        latest = self.build()["products"][0]["latest"]
        self.assertEqual(latest["linux-appimage"]["version"], "1.0.0-rc1")
        self.assertEqual(latest["linux-deb"]["url"], f"{BASE}/rusty-wave/latest/rusty-wave-latest_amd64.deb")
        self.assertEqual(latest["linux-deb"]["sig_url"], latest["linux-deb"]["url"] + ".asc")
        # rc1 dropped macOS: the alias still serves 0.0.5, and says so.
        self.assertEqual(latest["macos-dmg"]["version"], "0.0.5")
        self.assertNotIn("linux-appimage-zsync", latest)  # reached through zsync_url

    def test_rc_then_final_ordering(self):
        _, rf, lf = published("1.0.0")
        c = self.build(records=[self.r1, rf, self.r5], listing=self.listing + lf)
        p = c["products"][0]
        self.assertEqual([v["version"] for v in p["versions"]], ["1.0.0", "1.0.0-rc1", "0.0.5"])
        self.assertEqual(p["latest_version"], "1.0.0")
        self.assertEqual([v["prerelease"] for v in p["versions"]], [False, True, False])

    def test_record_file_missing_from_bucket(self):
        listing = [o for o in self.listing if not o["Key"].endswith("rusty-wave_1.0.0~rc1_amd64.deb")]
        with self.assertRaisesRegex(cat.CatalogError, "not in the bucket"):
            self.build(listing=listing)

    def test_size_mismatch(self):
        listing = [dict(o, Size=o["Size"] + 1) if o["Key"].endswith("rusty-wave-web-1.0.0-rc1.zip") else o
                   for o in self.listing]
        with self.assertRaisesRegex(cat.CatalogError, "bytes in the bucket"):
            self.build(listing=listing)

    def test_missing_signature(self):
        listing = [o for o in self.listing if not o["Key"].endswith("rusty-wave-1.0.0-rc1-x64-Setup.exe.asc")]
        with self.assertRaisesRegex(cat.CatalogError, r"\.asc: missing"):
            self.build(listing=listing)

    def test_version_without_record_stops_the_render(self):
        with self.assertRaisesRegex(cat.CatalogError, "no release record for 1.0.0-rc1"):
            self.build(records=[self.r5])

    def test_alias_matching_nothing(self):
        shas = dict(self.shas)
        shas["rusty-wave/latest/rusty-wave-latest_amd64.deb"] = "f" * 64
        with self.assertRaisesRegex(cat.CatalogError, "matches no published version"):
            self.build(shas=shas)

    def test_duplicate_or_foreign_record(self):
        with self.assertRaisesRegex(cat.CatalogError, "two records"):
            self.build(records=[self.r1, self.r1, self.r5])
        alien = dict(self.r1, product="other")
        with self.assertRaisesRegex(cat.CatalogError, "schema/product"):
            self.build(records=[alien, self.r5])

    def test_nothing_published_lists_no_product(self):
        c = cat.build_catalog([CONF], {}, [], {}, BASE, "2026-10-07T12:00:00Z")
        self.assertEqual(c["products"], [])

    def test_non_product_prefixes_are_ignored(self):
        listing = self.listing + [{"Key": "catalog/latest/catalog.json", "Size": 9},
                                  {"Key": "keys/rusty-wave-release-E13FF843.asc", "Size": 9},
                                  {"Key": "index.html", "Size": 9}]
        self.assertEqual(len(self.build(listing=listing)["products"]), 1)


if __name__ == "__main__":
    unittest.main()


class RealConfigTests(unittest.TestCase):
    """The shipped product config is valid for the catalog and matches the
    approved alias and label table in docs/catalog.md."""

    def setUp(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        self.conf = rc.load_conf(os.path.join(root, "scripts", "products", "rusty-wave.json"))
        with open(os.path.join(root, "docs", "catalog.md"), encoding="utf-8") as f:
            self.doc = f.read()

    def test_platforms_valid(self):
        self.assertEqual(list(cat._platforms(self.conf)), list(PLATFORMS))

    def test_every_platform_has_an_alias(self):
        self.assertEqual(set(self.conf["platforms"]) - set(self.conf["aliases"]), set())

    def test_aliases_and_labels_match_the_doc(self):
        import re
        table = dict(re.findall(r"^\| `([a-z-]+)` \| `([^`]+)`(?: \(\+ `\.zsync`\))? \|$", self.doc, re.M))
        self.assertEqual(table, {k: v for k, v in self.conf["aliases"].items() if k in self.conf["platforms"]})
        labels = dict(re.findall(r"^\| `([a-z-]+)` \| [a-z]+ \| [a-z]+ \| (.+) \|$", self.doc, re.M))
        self.assertEqual(labels, {k: v["label"] for k, v in self.conf["platforms"].items()})

    def test_aliases_are_all_latest_names(self):
        for alias in self.conf["aliases"].values():
            self.assertIn("latest", alias)
            self.assertNotIn("/", alias)


class CliTests(unittest.TestCase):
    def test_record_and_build_round_trip(self):
        import contextlib
        import io
        m, r, listing = published("1.0.0-rc1")
        with tempfile.TemporaryDirectory() as d:
            conf = os.path.join(d, "rusty-wave.json")
            with open(conf, "w") as f:
                json.dump(CONF, f)
            with open(os.path.join(d, "m.json"), "w") as f:
                json.dump(m, f)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(cat.main(["record", "--conf", conf, "--version", "1.0.0-rc1", "--manifest",
                                           os.path.join(d, "m.json"), "--commit", SHA_A, "--base-url", BASE]), 0)
            self.assertEqual(json.loads(buf.getvalue()), r)
            os.makedirs(os.path.join(d, "rec", "rusty-wave"))
            with open(os.path.join(d, "rec", "rusty-wave", "1.0.0-rc1.json"), "w") as f:
                f.write(buf.getvalue())
            with open(os.path.join(d, "listing.json"), "w") as f:
                json.dump(listing, f)
            with open(os.path.join(d, "sha.json"), "w") as f:
                json.dump({}, f)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cat.main(["build", "--confs", conf, "--listing", os.path.join(d, "listing.json"),
                                           "--alias-sha", os.path.join(d, "sha.json"), "--records",
                                           os.path.join(d, "rec"), "--base-url", BASE, "--generated", "t"]), 0)
            self.assertEqual(json.loads(out.getvalue())["products"][0]["latest_version"], "1.0.0-rc1")

    def test_build_failure_exits_2(self):
        import contextlib
        import io
        _, _, listing = published("1.0.0-rc1")
        with tempfile.TemporaryDirectory() as d:
            conf = os.path.join(d, "c.json")
            with open(conf, "w") as f:
                json.dump(CONF, f)
            with open(os.path.join(d, "l.json"), "w") as f:
                json.dump(listing, f)
            with open(os.path.join(d, "s.json"), "w") as f:
                json.dump({}, f)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc_ = cat.main(["build", "--confs", conf, "--listing", os.path.join(d, "l.json"), "--alias-sha",
                                os.path.join(d, "s.json"), "--records", os.path.join(d, "none"),
                                "--base-url", BASE, "--generated", "t"])
            self.assertEqual(rc_, 2)
            self.assertIn("no release record for 1.0.0-rc1", err.getvalue())


class PinnedKeyNameTests(unittest.TestCase):
    """The public key is published under a write-once name that carries the
    first 8 hex of the pinned key file's SHA-256, so they can't drift."""

    def test_key_url_path_matches_pinned_key(self):
        import hashlib
        root = os.path.join(os.path.dirname(__file__), "..")
        conf = rc.load_conf(os.path.join(root, "scripts", "products", "rusty-wave.json"))
        with open(os.path.join(root, conf["key_file"]), "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(conf["key_url_path"], f"keys/rusty-wave-release-E13FF843-{digest[:8]}.asc")
