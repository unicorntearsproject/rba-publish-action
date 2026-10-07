"""Offline tests for scripts/lib/release_check.py (run: python3 -m unittest discover tests)."""

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import release_check as rc  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
CONF = rc.load_conf(os.path.join(ROOT, "scripts", "products", "rusty-wave.json"))
BASE = "https://software.rustybucket.ai"
V = "0.0.5"


def web_zip(v, build_info=None):
    """The web-pwa zip, deterministic, optionally with build-info.json."""
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(zipfile.ZipInfo("index.html", (2026, 1, 1, 0, 0, 0)), f"<p>Rusty Wave {v}</p>")
        if build_info is not None:
            z.writestr(zipfile.ZipInfo("build-info.json", (2026, 1, 1, 0, 0, 0)), json.dumps(build_info))
    return buf.getvalue()


def make_release(d, v=V, base=BASE, skip=(), build_info=None):
    """A complete, consistent fake Rusty Wave release in directory d."""
    names = rc.expected_files(CONF, v)
    vdir = f"{base}/rusty-wave/{v}/"
    sums = []
    files = {}
    for pid, name in names.items():
        if pid in skip or pid == CONF["checksums_file"]:
            continue
        if pid == "linux-appimage-zsync":
            continue
        body = web_zip(v, build_info) if pid == "web-pwa" else f"{pid} {v} payload\n".encode() * 50
        with open(os.path.join(d, name), "wb") as f:
            f.write(body)
        sums.append((hashlib.sha256(body).hexdigest(), name))
        files[pid] = {
            "arch": "x86_64", "name": name, "url": vdir + name, "size": len(body),
            "sha256": hashlib.sha256(body).hexdigest(), "signature_url": vdir + name + ".asc",
        }
    if "linux-appimage" not in skip:
        appimage = names["linux-appimage"]
        zs = names["linux-appimage-zsync"]
        size = os.path.getsize(os.path.join(d, appimage))
        body = (f"zsync: 0.6.3\nFilename: {appimage}\nBlocksize: 2048\nLength: {size}\n"
                f"URL: {vdir}{appimage}\n\n").encode() + b"\x00" * 64
        with open(os.path.join(d, zs), "wb") as f:
            f.write(body)
        sums.append((hashlib.sha256(body).hexdigest(), zs))
        files["linux-appimage"]["zsync_url"] = f"{base}/rusty-wave/latest/rusty-wave-latest-x86_64.AppImage.zsync"
    with open(os.path.join(d, names["checksums"]), "w") as f:
        f.writelines(f"{h}  {n}\n" for h, n in sorted(sums, key=lambda x: x[1]))
    manifest = {"schema": 1, "version": v, "released": "2026-10-07",
                "key_fingerprint": CONF["key_fingerprint"], "files": files}
    with open(os.path.join(d, CONF["manifest"]), "w") as f:
        json.dump(manifest, f)
    for name in list(os.listdir(d)):
        with open(os.path.join(d, name + ".asc"), "w") as f:
            f.write("sig\n")
    return manifest


def write_manifest(d, m):
    with open(os.path.join(d, CONF["manifest"]), "w") as f:
        json.dump(m, f)


class VersionTests(unittest.TestCase):
    def test_strips_v(self):
        self.assertEqual(rc.normalize_version("v0.0.4"), "0.0.4")
        self.assertEqual(rc.normalize_version("0.0.4"), "0.0.4")

    def test_rejects_non_semver(self):
        for bad in ("0.4", "v1", "latest", "0.0.4/../x", ""):
            with self.assertRaises(rc.CheckError, msg=bad):
                rc.normalize_version(bad)

    def test_ordering(self):
        self.assertTrue(rc.semver_gt("0.0.10", "0.0.9"))
        self.assertTrue(rc.semver_gt("0.1.0", "0.0.99"))
        self.assertTrue(rc.semver_gt("1.0.0", "1.0.0-rc.2"))
        self.assertTrue(rc.semver_gt("1.0.0-rc.10", "1.0.0-rc.2"))
        self.assertFalse(rc.semver_gt("0.0.4", "0.0.4"))
        self.assertFalse(rc.semver_gt("0.0.3", "0.0.4"))


class PrereleaseTests(unittest.TestCase):
    RC1_NAMES = {  # RW's names for 1.0.0-rc1, verbatim
        "rusty-wave-1.0.0-rc1-x86_64.AppImage",
        "rusty-wave-1.0.0-rc1-x86_64.AppImage.zsync",
        "rusty-wave_1.0.0~rc1_amd64.deb",
        "rusty-wave-1.0.0-0.1.rc1.x86_64.rpm",
        "rusty-wave-1.0.0-rc1-linux-x86_64.tar.gz",
        "io.github.unicorntearsproject.RustyWave-1.0.0-rc1.flatpak",
        "rusty-wave-1.0.0-rc1-x64-Setup.exe",
        "rusty-wave-1.0.0-rc1-windows-x64.zip",
        "rusty-wave-1.0.0-rc1-macos-universal.dmg",
        "rusty-wave-web-1.0.0-rc1.zip",
        "rusty-wave-1.0.0-rc1-SHA256SUMS",
    }

    def test_rc_names_exact(self):
        self.assertEqual(set(rc.expected_files(CONF, "1.0.0-rc1").values()), self.RC1_NAMES)

    def test_final_and_old_names_unchanged(self):
        names = rc.expected_files(CONF, "0.0.4")
        self.assertEqual(names["linux-deb"], "rusty-wave_0.0.4_amd64.deb")
        self.assertEqual(names["linux-rpm"], "rusty-wave-0.0.4-1.x86_64.rpm")
        names = rc.expected_files(CONF, "1.0.0")
        self.assertEqual(names["linux-deb"], "rusty-wave_1.0.0_amd64.deb")
        self.assertEqual(names["linux-rpm"], "rusty-wave-1.0.0-1.x86_64.rpm")
        self.assertEqual(names["linux-appimage"], "rusty-wave-1.0.0-x86_64.AppImage")

    def test_dotted_prerelease_forms(self):
        f = rc.version_forms("1.0.0-rc.10")
        self.assertEqual((f["deb_v"], f["rpm_vr"]), ("1.0.0~rc.10", "1.0.0-0.1.rc.10"))

    def test_hyphen_in_prerelease_rejected_for_packages(self):
        with self.assertRaisesRegex(rc.CheckError, "deb and rpm"):
            rc.expected_files(CONF, "1.0.0-rc-1")

    def test_grammar(self):
        for good in ("v1.0.0-rc1", "1.0.0-rc.10", "1.0.0-alpha.1", "1.0.0-0.3.7", "1.0.0-x.7.z.92", "10.20.30"):
            rc.normalize_version(good)
        for bad in ("1.0.0+build.1", "1.0.0-rc1+b", "01.0.0", "1.00.0", "1.0.0-rc.01", "1.0.0-",
                    "1.0.0-rc..1", "1.0.0-rc_1", "1.0.0-rc/1", "1.0", "v1.0.0-rc 1"):
            with self.assertRaises(rc.CheckError, msg=bad):
                rc.normalize_version(bad)

    def test_precedence_table(self):
        # SemVer 2.0 section 11 example, then RW's cases.
        ordered = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta",
                   "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]
        for lo, hi in zip(ordered, ordered[1:]):
            self.assertTrue(rc.semver_gt(hi, lo), f"{hi} > {lo}")
            self.assertFalse(rc.semver_gt(lo, hi), f"not {lo} > {hi}")
        for hi, lo in (("1.0.0-rc1", "0.0.4"), ("1.0.0-rc2", "1.0.0-rc1"), ("1.0.0", "1.0.0-rc9"),
                       ("1.0.0-rc.10", "1.0.0-rc.9"), ("1.0.1-rc1", "1.0.0"), ("2.0.0-alpha", "1.99.99")):
            self.assertTrue(rc.semver_gt(hi, lo), f"{hi} > {lo}")

    def test_rc10_trap(self):
        # "rc10" is one alphanumeric identifier, compared as text: it sorts
        # BEFORE "rc9". Use "rc.10" (or stay below 10).
        self.assertTrue(rc.semver_gt("1.0.0-rc9", "1.0.0-rc10"))
        self.assertTrue(rc.semver_gt("1.0.0-rc.10", "1.0.0-rc.9"))

    def release(self, v, live):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        make_release(tmp.name, v=v)
        rc.check_names(CONF, tmp.name, v)
        rc.check_checksums(CONF, tmp.name, v)
        return rc.check_manifest(CONF, tmp.name, v, BASE, live_manifest=None if live is None else {"version": live})

    def test_rc_publishes_over_older_final(self):
        self.release("1.0.0-rc1", "0.0.4")
        self.release("1.0.0-rc1", None)

    def test_rc_to_rc_and_rc_to_final(self):
        self.release("1.0.0-rc2", "1.0.0-rc1")
        self.release("1.0.0", "1.0.0-rc9")

    def test_downgrades_rejected(self):
        for v, live in (("1.0.0-rc1", "1.0.0"), ("1.0.0-rc1", "1.0.0-rc2"), ("1.0.0-rc1", "1.0.0-rc1"),
                        ("0.0.4", "1.0.0-rc1")):
            with self.assertRaisesRegex(rc.CheckError, "not newer", msg=f"{v} over {live}"):
                self.release(v, live)


class ContentTypeTests(unittest.TestCase):
    def test_binaries_are_not_compressible(self):
        self.assertEqual(rc.content_type("rusty-wave-0.0.4-x86_64.AppImage"), "application/octet-stream")
        self.assertEqual(rc.content_type("rusty-wave-0.0.4-x86_64.AppImage.zsync"), "application/x-zsync")
        self.assertEqual(rc.content_type("rusty-wave-0.0.4-x86_64.AppImage.asc"), "application/pgp-signature")
        self.assertEqual(rc.content_type("rusty-wave-0.0.4-SHA256SUMS"), "text/plain; charset=utf-8")

    def test_every_listed_file_has_a_type(self):
        for name in rc.expected_files(CONF, "0.0.4").values():
            rc.content_type(name)
            rc.content_type(name + ".asc")


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.m = make_release(self.d)

    def tearDown(self):
        self.tmp.cleanup()

    def test_good_release_passes(self):
        files = rc.check_names(CONF, self.d, V)
        self.assertNotIn(CONF["manifest"], files)
        self.assertIn("rusty-wave-0.0.5-x86_64.AppImage.asc", files)
        rc.check_checksums(CONF, self.d, V)
        rc.check_manifest(CONF, self.d, V, BASE, live_manifest={"version": "0.0.4"})

    def test_first_publish_has_no_live_manifest(self):
        rc.check_manifest(CONF, self.d, V, BASE, live_manifest=None)

    def test_unlisted_file_rejected(self):
        for stray in ("index.html", "rusty-wave-latest-x86_64.AppImage", "notes.txt"):
            open(os.path.join(self.d, stray), "w").close()
            open(os.path.join(self.d, stray + ".asc"), "w").close()
            with self.assertRaisesRegex(rc.CheckError, "not on the"):
                rc.check_names(CONF, self.d, V)
            os.remove(os.path.join(self.d, stray))
            os.remove(os.path.join(self.d, stray + ".asc"))

    def test_missing_signature_rejected(self):
        os.remove(os.path.join(self.d, "rusty-wave_0.0.5_amd64.deb.asc"))
        with self.assertRaisesRegex(rc.CheckError, "missing rusty-wave_0.0.5_amd64.deb.asc"):
            rc.check_names(CONF, self.d, V)

    def test_wrong_version_names_rejected(self):
        with self.assertRaises(rc.CheckError):
            rc.check_names(CONF, self.d, "0.0.6")

    def test_symlink_rejected(self):
        os.symlink("/etc/hostname", os.path.join(self.d, "rusty-wave-web-0.0.5.zip.lnk"))
        with self.assertRaisesRegex(rc.CheckError, "not a regular file"):
            rc.check_names(CONF, self.d, V)

    def test_appimage_without_zsync_rejected(self):
        os.remove(os.path.join(self.d, "rusty-wave-0.0.5-x86_64.AppImage.zsync"))
        os.remove(os.path.join(self.d, "rusty-wave-0.0.5-x86_64.AppImage.zsync.asc"))
        with self.assertRaisesRegex(rc.CheckError, "published together"):
            rc.check_names(CONF, self.d, V)

    def test_partial_platform_set_allowed(self):
        tmp = tempfile.TemporaryDirectory()
        make_release(tmp.name, skip=("macos-dmg",))
        rc.check_names(CONF, tmp.name, V)
        rc.check_manifest(CONF, tmp.name, V, BASE)
        tmp.cleanup()

    def test_tampered_file_fails_checksums(self):
        with open(os.path.join(self.d, "rusty-wave_0.0.5_amd64.deb"), "ab") as f:
            f.write(b"x")
        with self.assertRaisesRegex(rc.CheckError, "SHA-256 differs"):
            rc.check_checksums(CONF, self.d, V)

    def test_unlisted_in_sha256sums_fails(self):
        p = os.path.join(self.d, "rusty-wave-0.0.5-SHA256SUMS")
        with open(p) as f:
            lines = [l for l in f if "flatpak" not in l]
        with open(p, "w") as f:
            f.writelines(lines)
        with self.assertRaisesRegex(rc.CheckError, "not listed"):
            rc.check_checksums(CONF, self.d, V)

    def test_manifest_not_newer_fails(self):
        for live in ("0.0.5", "0.0.6", "1.0.0"):
            with self.assertRaisesRegex(rc.CheckError, "not newer"):
                rc.check_manifest(CONF, self.d, V, BASE, live_manifest={"version": live})

    def test_manifest_tampering_fails(self):
        cases = [
            ("schema", lambda m: m.update(schema=2), "schema"),
            ("version", lambda m: m.update(version="0.0.6"), "version"),
            ("key", lambda m: m.update(key_fingerprint="0" * 40), "key_fingerprint"),
            ("old host", lambda m: m["files"]["linux-deb"].update(
                url="https://example-bucket.s3.amazonaws.com/rusty-wave_0.0.5_amd64.deb"), "url"),
            ("latest url", lambda m: m["files"]["linux-deb"].update(
                url=f"{BASE}/rusty-wave/latest/rusty-wave_0.0.5_amd64.deb"), "url"),
            ("sig url", lambda m: m["files"]["linux-rpm"].update(signature_url="x"), "signature_url"),
            ("size", lambda m: m["files"]["linux-rpm"].update(size=1), "size"),
            ("sha", lambda m: m["files"]["linux-rpm"].update(sha256="0" * 64), "sha256"),
            ("zsync url", lambda m: m["files"]["linux-appimage"].update(zsync_url=f"{BASE}/x.zsync"), "zsync_url"),
            ("zsync elsewhere", lambda m: m["files"]["linux-deb"].update(
                zsync_url=f"{BASE}/rusty-wave/latest/rusty-wave-latest-x86_64.AppImage.zsync"), "zsync_url"),
            ("renamed", lambda m: m["files"]["linux-deb"].update(name="evil.deb"), "doesn't match"),
            ("empty", lambda m: m.update(files={}), "files is empty"),
        ]
        for label, mutate, msg in cases:
            m = copy.deepcopy(self.m)
            mutate(m)
            write_manifest(self.d, m)
            with self.assertRaisesRegex(rc.CheckError, msg, msg=label):
                rc.check_manifest(CONF, self.d, V, BASE)
        write_manifest(self.d, self.m)

    def test_zsync_must_point_at_versioned_appimage(self):
        zs = os.path.join(self.d, "rusty-wave-0.0.5-x86_64.AppImage.zsync")
        with open(zs, "rb") as f:
            body = f.read()
        for bad in (b"URL: https://example-bucket.s3.amazonaws.com/rusty-wave-0.0.5-x86_64.AppImage",
                    b"URL: rusty-wave-0.0.5-x86_64.AppImage",
                    b"URL: https://software.rustybucket.ai/rusty-wave/latest/rusty-wave-latest-x86_64.AppImage"):
            start = body.index(b"URL: ")
            end = body.index(b"\n", start)
            with open(zs, "wb") as f:
                f.write(body[:start] + bad + body[end:])
            with self.assertRaisesRegex(rc.CheckError, "URL is", msg=bad):
                rc.check_manifest(CONF, self.d, V, BASE)
        with open(zs, "wb") as f:
            f.write(body.replace(b"Length: ", b"Length: 9"))
        with self.assertRaisesRegex(rc.CheckError, "Length"):
            rc.check_manifest(CONF, self.d, V, BASE)


class CommitTests(unittest.TestCase):
    SHA = "d5f5935dc3a28d249baeae6236b345dc3b07f3b5"

    def release(self, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        make_release(tmp.name, **kw)
        return tmp.name

    def test_no_commit_named(self):
        self.assertEqual(rc.release_commits(CONF, self.release(), V), [])

    def test_build_info_commit(self):
        d = self.release(build_info={"version": V, "commit": self.SHA})
        self.assertEqual(rc.release_commits(CONF, d, V), [("rusty-wave-web-0.0.5.zip:build-info.json", self.SHA)])

    def test_manifest_commit(self):
        d = self.release()
        p = os.path.join(d, CONF["manifest"])
        with open(p) as f:
            m = json.load(f)
        m["commit"] = self.SHA
        write_manifest(d, m)
        self.assertEqual(rc.release_commits(CONF, d, V), [(CONF["manifest"], self.SHA)])

    def test_build_info_version_must_match(self):
        d = self.release(build_info={"version": "0.0.4", "commit": self.SHA})
        with self.assertRaisesRegex(rc.CheckError, "says version"):
            rc.release_commits(CONF, d, V)

    def test_short_or_bad_sha_rejected(self):
        for bad in ("d5f5935", "D5F5935DC3A28D249BAEAE6236B345DC3B07F3B5", 42):
            d = self.release(build_info={"version": V, "commit": bad})
            with self.assertRaisesRegex(rc.CheckError, "full SHA-1"):
                rc.release_commits(CONF, d, V)


class RangeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.data = bytes(range(256)) * 64
        self.tmp.write(self.data)
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def multipart(self, ranges, boundary="CloudFrontBoundary", tamper=False):
        body = b""
        for a, b in ranges:
            chunk = self.data[a:b + 1]
            if tamper:
                chunk = b"x" + chunk[1:]
            body += (f"\r\n--{boundary}\r\nContent-Type: application/octet-stream\r\n"
                     f"Content-Range: bytes {a}-{b}/{len(self.data)}\r\n\r\n").encode() + chunk
        body += f"\r\n--{boundary}--\r\n".encode()
        headers = f"HTTP/2 206\r\ncontent-type: multipart/byteranges; boundary={boundary}\r\n\r\n"
        return headers, body

    def test_single_range(self):
        h = f"HTTP/2 206\r\ncontent-range: bytes 100-199/{len(self.data)}\r\n\r\n"
        self.assertIn("bytes match", rc.check_range_response(self.tmp.name, h, self.data[100:200], [(100, 199)]))
        with self.assertRaisesRegex(rc.CheckError, "differ"):
            rc.check_range_response(self.tmp.name, h, self.data[101:201], [(100, 199)])

    def test_multipart(self):
        rs = [(0, 1023), (4096, 8191)]
        h, b = self.multipart(rs)
        self.assertIn("2 parts", rc.check_range_response(self.tmp.name, h, b, rs))
        h, b = self.multipart(rs, tamper=True)
        with self.assertRaisesRegex(rc.CheckError, "differ"):
            rc.check_range_response(self.tmp.name, h, b, rs)

    def test_cold_edge_whole_object_is_reported(self):
        h = "HTTP/2 200\r\ncontent-type: application/octet-stream\r\n\r\n"
        with self.assertRaisesRegex(rc.CheckError, r"HTTP 200 \(the whole object\)"):
            rc.check_range_response(self.tmp.name, h, self.data, [(0, 1023), (4096, 8191)])

    def test_hex_to_b64(self):
        self.assertEqual(rc.hex_to_b64("00" * 32), "A" * 43 + "=")


class IndexTests(unittest.TestCase):
    def test_pages_and_ordering(self):
        listing = [
            {"Key": "rusty-wave/0.0.4/rusty-wave_0.0.4_amd64.deb", "Size": 5100412, "LastModified": "2026-10-06T15:00:00Z"},
            {"Key": "rusty-wave/0.0.10/rusty-wave_0.0.10_amd64.deb", "Size": 10, "LastModified": "2026-11-01T00:00:00Z"},
            {"Key": "rusty-wave/latest/rusty-wave-latest.json", "Size": 3, "LastModified": "2026-11-01T00:00:00Z"},
            {"Key": "rusty-wave/0.0.4/index.html", "Size": 1, "LastModified": "2026-10-06T15:00:00Z"},
        ]
        pages = rc.build_indexes(listing, {"rusty-wave": "Rusty Wave"}, {"rusty-wave": CONF["key_fingerprint"]})
        self.assertEqual(set(pages), {"index.html", "rusty-wave/index.html", "rusty-wave/latest/index.html",
                                      "rusty-wave/0.0.4/index.html", "rusty-wave/0.0.10/index.html"})
        product = pages["rusty-wave/index.html"]
        self.assertLess(product.index("latest/"), product.index("0.0.10/"))
        self.assertLess(product.index("0.0.10/"), product.index("0.0.4/"))
        self.assertIn("E13F F843 723D 5406 8E45 A3FF 54BF 2FA4 0709 3CEE", product)
        self.assertIn("5,100,412", pages["rusty-wave/0.0.4/index.html"])
        self.assertNotIn('href="index.html"', pages["rusty-wave/0.0.4/index.html"])
        self.assertNotIn("<script", "".join(pages.values()))

    def test_prerelease_ordering(self):
        listing = [{"Key": f"rusty-wave/{v}/x.zip", "Size": 1, "LastModified": "2026-10-06T00:00:00Z"}
                   for v in ("0.0.4", "1.0.0-rc1", "1.0.0", "1.0.0-rc2")]
        page = rc.build_indexes(listing, {"rusty-wave": "Rusty Wave"}, {})["rusty-wave/index.html"]
        pos = [page.index(f'href="{v}/"') for v in ("1.0.0", "1.0.0-rc2", "1.0.0-rc1", "0.0.4")]
        self.assertEqual(pos, sorted(pos))

    def test_kit_stylesheet_and_folders_only(self):
        listing = [{"Key": f"rusty-wave/{k}", "Size": 1, "LastModified": "2026-10-07T00:00:00Z"}
                   for k in ("1.0.0-rc1/x.zip", "latest/rusty-wave-latest.json")]
        pages = rc.build_indexes(listing, {"rusty-wave": "Rusty Wave"}, {},
                                 stylesheet="/_kit/kit.a210dba0f2.css", folders_only=True)
        self.assertEqual(set(pages), {"rusty-wave/1.0.0-rc1/index.html", "rusty-wave/latest/index.html"})
        for page in pages.values():
            self.assertIn('<link rel="stylesheet" href="/_kit/kit.a210dba0f2.css">', page)
            self.assertNotIn("<style", page)
            self.assertNotIn(" style=", page)

    def test_default_keeps_inline_style(self):
        page = rc.render_index("t", [])
        self.assertIn("<style>", page)
        self.assertNotIn("{{", page)

    def test_names_are_escaped(self):
        listing = [{"Key": "rusty-wave/0.0.4/a<b>.zip", "Size": 1, "LastModified": "2026-10-06T00:00:00Z"}]
        page = rc.build_indexes(listing, {"rusty-wave": "Rusty Wave"}, {})["rusty-wave/0.0.4/index.html"]
        self.assertIn("a&lt;b&gt;.zip", page)
        self.assertNotIn("a<b>.zip", page)


if __name__ == "__main__":
    unittest.main()
