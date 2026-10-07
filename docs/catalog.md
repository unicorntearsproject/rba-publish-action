[rba-publish-action](../README.md) › [Docs](README.md) › Catalog

# `catalog.json` (schema 1)

The installers pages' data: `catalog/latest/catalog.json`, rebuilt from every
release record after each publish. Additive changes only within schema 1.
Code: `scripts/lib/catalog.py` (tests: `tests/test_catalog.py`).

`https://software.rustybucket.ai/catalog/latest/catalog.json` lists every product and every
published version, for the installers page (rendered by `publish-release.sh`
and `render-index`) and anyone else who wants a machine-readable index.
`Cache-Control: public, max-age=60`, like the manifest.

## Where the data comes from

Only the latest manifest is kept, and replaced objects expire after 30 days,
so the catalog can't be rebuilt from old manifests. Instead each verified
publish writes an **immutable release record**,
`<product>/<version>/release.json` (`If-None-Match`, never overwritten),
holding the fields below for that version. It's written only after the
publish has checked every file in the bucket by size and SHA-256, and the
files can never change afterwards.

`catalog.json` is the aggregate of all release records, cross-checked
against the bucket listing at render time (every file present, same size),
plus the current `latest/` aliases, each matched to the version it serves by
SHA-256. A version without a record, or a record that doesn't match the
bucket, stops the render; it is never silently dropped.

## Example

```json
{
  "schema": 1,
  "generated": "2026-10-07T12:00:00Z",
  "base_url": "https://software.rustybucket.ai",
  "products": [
    {
      "id": "rusty-wave",
      "name": "Rusty Wave",
      "key_fingerprint": "E13FF843723D54068E45A3FF54BF2FA407093CEE",
      "key_url": "https://software.rustybucket.ai/keys/rusty-wave-release-E13FF843.asc",
      "manifest_url": "https://software.rustybucket.ai/rusty-wave/latest/rusty-wave-latest.json",
      "latest_version": "1.0.0-rc1",
      "latest": {
        "linux-appimage": {
          "name": "rusty-wave-latest-x86_64.AppImage",
          "url": "https://software.rustybucket.ai/rusty-wave/latest/rusty-wave-latest-x86_64.AppImage",
          "sig_url": "https://software.rustybucket.ai/rusty-wave/latest/rusty-wave-latest-x86_64.AppImage.asc",
          "version": "1.0.0-rc1"
        }
      },
      "versions": [
        {
          "version": "1.0.0-rc1",
          "prerelease": true,
          "tag": "v1.0.0-rc1",
          "commit": "d5f5935dc3a28d249baeae6236b345dc3b07f3b5",
          "released": "2026-10-07",
          "url": "https://software.rustybucket.ai/rusty-wave/1.0.0-rc1/",
          "checksums_url": "https://software.rustybucket.ai/rusty-wave/1.0.0-rc1/rusty-wave-1.0.0-rc1-SHA256SUMS",
          "checksums_sig_url": "https://software.rustybucket.ai/rusty-wave/1.0.0-rc1/rusty-wave-1.0.0-rc1-SHA256SUMS.asc",
          "files": [
            {
              "platform_id": "linux-appimage",
              "os": "linux",
              "arch": "x86_64",
              "kind": "portable",
              "label": "AppImage",
              "name": "rusty-wave-1.0.0-rc1-x86_64.AppImage",
              "url": "https://software.rustybucket.ai/rusty-wave/1.0.0-rc1/rusty-wave-1.0.0-rc1-x86_64.AppImage",
              "size": 6924792,
              "sha256": "4700c72f0e87b1fd310dbf72d5346736a1d91668706a026dc3c544febc8fd689",
              "sig_url": "https://software.rustybucket.ai/rusty-wave/1.0.0-rc1/rusty-wave-1.0.0-rc1-x86_64.AppImage.asc",
              "zsync_url": "https://software.rustybucket.ai/rusty-wave/latest/rusty-wave-latest-x86_64.AppImage.zsync"
            }
          ]
        }
      ]
    }
  ]
}
```

## Fields

**Top level**

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | integer | `1`. Additive changes keep `1`; anything that removes or changes the meaning of a field bumps it |
| `generated` | string | UTC time of this render, RFC 3339 |
| `base_url` | string | `https://software.rustybucket.ai` |
| `products` | array | In product-config order (Rusty Wave first) |

**Product**

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Product id and path prefix (`rusty-wave`) |
| `name` | string | Display name (`Rusty Wave`) |
| `key_fingerprint` | string | 40 hex, no spaces; the key every `.asc` is checked against |
| `key_url` | string | The public key, published once under a fingerprinted name (proposed; see questions) |
| `manifest_url` | string | The publisher's signed `-latest.json` |
| `latest_version` | string | Newest published version (SemVer precedence, pre-releases included) |
| `latest` | object | `platform_id` → stable alias: `name`, `url`, `sig_url`, and `version`, the version the alias serves now (matched by SHA-256). The links the main site's summary uses |
| `versions` | array | Every published version, **newest first** by SemVer precedence |

**Version**

| Field | Type | Meaning |
| --- | --- | --- |
| `version` | string | SemVer without `v` (`1.0.0-rc1`) |
| `prerelease` | boolean | `true` if it has a pre-release part |
| `tag` | string | The git tag it was published from (`v1.0.0-rc1`) |
| `commit` | string | 40-hex commit the tag points to (from the tag gate) |
| `released` | string | The publisher's `released` from its manifest, as given (`YYYY-MM-DD`) |
| `url` | string | The version folder (its own listing page) |
| `checksums_url`, `checksums_sig_url` | string | `SHA256SUMS` and its signature |
| `files` | array | Downloadable files in product-config order (`SHA256SUMS`, `.asc` and `.zsync` aren't separate entries) |

**File**

| Field | Type | Meaning |
| --- | --- | --- |
| `platform_id` | string | Stable id from the product config (`linux-deb`) |
| `os` | string | `linux` · `windows` · `macos` · `any` |
| `arch` | string | As the publisher's manifest says (`x86_64`, `amd64`, `x64`, `universal`, `any`) |
| `kind` | string | `installer` · `portable` · `package` · `web` |
| `label` | string | Short human label (`AppImage`, `Debian/Ubuntu (.deb)`) |
| `name`, `url` | string | Exact versioned file name and its permanent URL |
| `size` | integer | Bytes, as stored |
| `sha256` | string | 64 hex |
| `sig_url` | string | Detached signature |
| `zsync_url` | string, optional | AppImage only: the stable `.zsync` alias |
| `note` | string, optional | The publisher's note, verbatim (for example the macOS beta note) |

Rusty Wave's platforms:

| `platform_id` | `os` | `kind` | `label` |
| --- | --- | --- | --- |
| `linux-appimage` | linux | portable | AppImage |
| `linux-deb` | linux | package | Debian/Ubuntu (.deb) |
| `linux-rpm` | linux | package | Fedora/RHEL (.rpm) |
| `linux-flatpak` | linux | package | Flatpak |
| `linux-tarball` | linux | portable | Linux tarball (.tar.gz) |
| `windows-installer` | windows | installer | Windows installer (.exe) |
| `windows-portable` | windows | portable | Windows portable (.zip) |
| `macos-dmg` | macos | installer | macOS (.dmg) |
| `web-pwa` | any | web | Web app (.zip) |

## `latest/` aliases (stable URLs for the main site)

`https://software.rustybucket.ai/rusty-wave/latest/<alias>`, each with `.asc`:

| `platform_id` | Alias |
| --- | --- |
| `linux-appimage` | `rusty-wave-latest-x86_64.AppImage` (+ `.zsync`) |
| `linux-deb` | `rusty-wave-latest_amd64.deb` |
| `linux-rpm` | `rusty-wave-latest.x86_64.rpm` |
| `linux-flatpak` | `io.github.unicorntearsproject.RustyWave-latest.flatpak` |
| `linux-tarball` | `rusty-wave-latest-linux-x86_64.tar.gz` |
| `windows-installer` | `rusty-wave-latest-x64-Setup.exe` |
| `windows-portable` | `rusty-wave-latest-windows-x64.zip` |
| `macos-dmg` | `rusty-wave-latest-macos-universal.dmg` |
| `web-pwa` | `rusty-wave-web-latest.zip` |

No alias for `SHA256SUMS`: its lines name the versioned files, so it would
mislead under a `latest` name. The signed manifest is the "latest" index.

## Decisions (2026-10-06)

1. **URL:** `/catalog/latest/catalog.json`, which the bucket policy's existing
   `*/latest/*` exception already covers, so the policy isn't loosened.
   Checked with IAM's policy simulator against the live policy (an
   unconditional put is allowed there and denied on `catalog/catalog.json`,
   `catalog.json` and `catalog/latest-x/…`) and with live puts on the two
   neighbours, refused with nothing created. A CloudFront Function rewrite
   from `/catalog.json` may come later.
2. **Dropped platforms:** the catalog keeps each alias's actual `version`.
   The full page shows only the current version's files, and omits any
   alias whose `version` isn't `latest_version`. The main site's summary
   lists platforms in its own display data; dropping one is a content
   update there.
3. **`key_url`:** the public key is published once, at
   `/keys/rusty-wave-release-E13FF843.asc` (`If-None-Match`, immutable).
4. **Versions without a record:** if a version is published before release
   records exist (`1.0.0-rc1` may be), `render-index` writes its record from
   the live signed manifest with the full publish checks, only while that
   version is the latest, and logs it loudly.

**Related:** [Publishing](publishing.md) · [README](../README.md)
