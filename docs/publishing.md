[rba-publish-action](../README.md) › [Docs](README.md) › Publishing

# Publishing a release

How `scripts/publish-release.sh` (and the action, which runs it) checks and
publishes a release, and how `scripts/render-index.sh` re-renders the site.

## Modes

```bash
scripts/publish-release.sh rusty-wave v1.0.0-rc1 <release-dir> --preflight # file checks only, no tag needed
scripts/publish-release.sh rusty-wave v1.0.0-rc1 <release-dir> --dry-run   # every check, incl. the tag gate
RBA_SETTINGS=<settings file> scripts/publish-release.sh rusty-wave v1.0.0-rc1 <release-dir>   # publish
```

- `--preflight` runs the file checks (names, signatures, `SHA256SUMS`, the
  manifest with its zsync header, newer than live), then stops before the
  tag gate with a `preflight only` line. It makes no `aws` or `gh` calls.
  It is a check before tagging, never a substitute for the dry run on the tag.
- `--dry-run` runs every check, including the tag gate, and prints the
  keys it would write. It needs no AWS access and no settings.
- A publish needs the deployment's settings (`RBA_SETTINGS`, see
  [`scripts/lib/settings.sh`](../scripts/lib/settings.sh)): the bucket and
  the distribution, plus a local AWS profile and role, or `--ci` with the
  credentials already in the environment.

It needs `aws` (CLI v2 with `put-object --if-none-match`), `gh`, `gpg`, `jq`,
`curl` (7.81 or newer; it logs which), `openssl` and `python3`. The script
checks them first.

Every request the scripts make to the site sends the User-Agent
`rba-publish-verify/1`, so the site's usage report counts it as our own
automation, not a download.

Each run works in its own `mktemp` directory (`$TMPDIR` or `/tmp`) with a
throwaway keyring. On exit, even on failure, it stops that keyring's
`gpg-agent` and removes the directory: only a `/tmp/rba-<name>` directory
it owns, never a symlink, never anything outside `/tmp`
([`scripts/lib/scratch.sh`](../scripts/lib/scratch.sh)).

## What the release directory must contain

- The release files, **only** names from the product's list
  ([`scripts/products/rusty-wave.json`](../scripts/products/rusty-wave.json)),
  with `<v>` the version without the `v`: SemVer 2.0, optionally a
  pre-release (`1.0.0-rc1`), no build metadata. Debian and RPM files use
  their own spellings (`rusty-wave_1.0.0~rc1_amd64.deb`,
  `rusty-wave-1.0.0-0.1.rc1.x86_64.rpm`; finals `…_1.0.0_…`, `…-1.0.0-1…`).
  Every tagged release, pre-releases included, moves `latest/`, as long as
  it is newer than the live version by SemVer precedence. **Write
  `rc.10`, not `rc10`:** `rc10` is a single text identifier and sorts
  *before* `rc9`, so it would be refused as older.
- A detached `.asc` next to **every** file, by the pinned key or one of its
  signing subkeys ([keys](../keys/README.md)): exactly one signature per
  `.asc`, by a key that is neither expired nor revoked.
- `rusty-wave-<v>-SHA256SUMS` (+ `.asc`), listing every release file.
- `rusty-wave-latest.json` (+ `.asc`), the signed manifest, with every
  `url`/`signature_url` at `https://software.rustybucket.ai/rusty-wave/<v>/<name>`
  and `zsync_url` at
  `https://software.rustybucket.ai/rusty-wave/latest/rusty-wave-latest-x86_64.AppImage.zsync`.
- The AppImage and its `.zsync` together; the `.zsync` `URL:` header must be
  `https://software.rustybucket.ai/rusty-wave/<v>/rusty-wave-<v>-x86_64.AppImage`.

Nothing else: no `index.html`, no `-latest` files, no subdirectories.

## What it does

1. Checks names, every signature (throwaway keyring, pinned fingerprint),
   `SHA256SUMS`, the manifest against the local files and the live
   manifest (the version must be newer). Only S3's own answer for a
   missing key (a 403 with its `AccessDenied` XML, `server: AmazonS3`)
   counts as "nothing live yet". Any other answer stops the publish rather
   than skip the newer-than-live check: a CloudFront or WAF 403, a 404, a
   5xx, or a timeout. Then the **tag**: `v<version>`
   must exist in the source repo, and any commit the release names
   (`build-info.json` in the web zip, or a manifest `commit`) must be the
   tag's commit. **Nothing is uploaded until all of this passes.** If
   GitHub can't be reached, it stops.
2. Gets the publish role's credentials for its own process (in CI: checks
   that the job is running as the role the settings name).
3. Uploads every versioned file with `If-None-Match: *` and its SHA-256.
   A file already there with the same hash (an interrupted earlier run) is
   accepted; a different one aborts.
4. Checks every manifest file in the bucket by size and SHA-256, then
   writes the version's immutable release record
   (`<product>/<version>/release.json`) and, once ever, the public key.
   Before any upload it has also checked that every older version already
   has its record, so the catalog can be rebuilt afterwards.
5. Replaces the `latest/` aliases (one per platform, stored with their
   SHA-256), then the manifest `.asc`, then the manifest, unchanged; then
   rebuilds `catalog/latest/catalog.json` from every release record
   ([schema](catalog.md)) and renders the installers pages with the
   vendored page kit ([vendor](../vendor/README.md)), checked against its
   manifest first.
6. Invalidates the CDN cache.
7. Verifies through `https://software.rustybucket.ai/`: the manifest bytes,
   every manifest URL and its length, the aliases' hashes, single and
   multi-range requests, and that an overwrite of a published file is
   refused.
8. Prints a `CHANGELOG:` line for the publisher's changelog.
9. Starts the product's downstream deploy workflow, if configured
   (`notify` in the product config). If that fails, it prints a loud WARN
   and the exact command to retry; the publish itself still succeeds. It
   notifies **even when step 7 failed**: the release is already public,
   its files were verified before upload and in the bucket, and the
   downstream verifies what it fetches itself. The run then still fails,
   so a person looks.

## In GitHub Actions

See the [README](../README.md#use) for the inputs. The action:

1. masks the role ARN and its account ID (from the caller's secret);
2. checks its inputs; `dry-run` and `preflight` must be `true` or `false`;
3. prints the SHA-256 of everything it runs;
4. for a publish only: assumes the role through GitHub OIDC (masking the
   account ID), reads the bucket and the distribution from the SSM
   parameter, masks both, and writes the settings file
   ([`scripts/ci-settings.sh`](../scripts/ci-settings.sh));
5. runs `publish-release.sh --ci`.

Nothing in the publish path traces commands: `set -x` would print masked
values in the clear. The offline tests check this, and check that no
scenario's log (after GitHub's masking) contains an account ID, an ARN with
an account in it, or a deployment value.

## Re-rendering without publishing: `render-index`

```bash
RBA_SETTINGS=<settings file> scripts/render-index.sh --dry-run   # report, check the catalog builds, write nothing
RBA_SETTINGS=<settings file> scripts/render-index.sh             # backfill (if allowed), catalog, pages, invalidate, verify
```

It rebuilds the catalog and the installers pages from the live bucket,
and publishes any product's missing public key (once). With nothing
published yet it writes an empty catalog and renders no pages. A version
folder without a release record is **backfilled** only if it is the version
the live signed manifest names: its files are fetched from the bucket and
put through the same checks as a publish, and the backfill is logged
loudly. Any other version without a record stops the render.

## If it fails

| Where | Meaning | What to do |
| --- | --- | --- |
| The file checks | Nothing was uploaded | Fix the release directory and re-run |
| "only tagged versions publish" | No `v<version>` tag, or GitHub unreachable | Push the tag (or retry later); nothing was uploaded |
| "names commit …, but v… is …" | The build isn't the tagged commit | Rebuild from the tag; nothing was uploaded |
| "… is not set: point RBA_SETTINGS …" | A publish without the deployment's settings | Nothing was uploaded; give the settings |
| "WARN … notifying … FAILED" | Published; the downstream wasn't told | Run the printed retry command |
| "no release record for …: run scripts/render-index.sh first" | An older version predates release records; nothing was uploaded | Run `render-index`, then publish again |
| "not newer than the live" | That version (or a newer one) is already live | Nothing; a version is published once |
| "live manifest answered HTTP …" / "can't fetch the live manifest" | The live manifest couldn't be read reliably (a CDN or WAF block, an error, a timeout); nothing was uploaded | Find out why the site answered that way, then re-run |
| "already exists with different content" | A published version can't change | Release a new version |
| After uploads, before the manifest | Versioned files are there, `latest/` unchanged | Re-run the same command: identical files are accepted |
| "published and notified, but verification FAILED" | Published, and the downstream was told; a CDN check didn't pass | Report it to the site's maintainers |

**Related:** [README](../README.md) · [Catalog](catalog.md) ·
[Keys](../keys/README.md) · [Vendor](../vendor/README.md)
