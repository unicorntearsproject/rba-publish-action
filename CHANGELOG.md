# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Callers pin commit SHAs; each entry names what changed for them.

## [Unreleased]

### Added

- Page kit re-vendored at website-primary `32cf021` (manifest `123a990`, 24 files):
  the Corporate mode switch and theme (one first-party script, `mode.js`,
  so the site's CSP needs `script-src 'self'`) and each product's
  "Source code: fully audited & tested by AI" link, from the catalog's
  `source_url`. The offline suite checks the link and allows only
  `src=` scripts. See [vendor](vendor/README.md).
- `source_repo` is required in every product config (`load_conf` refuses a
  config without a valid `owner/name`), and each catalog product carries
  `source_repo` and `source_url` (`https://github.com/<repo>`), so every
  product on the downloads page can link its source. Additive; schema stays 1.
- A second product, U-Stu Video Editor (`scripts/products/u-studio-video-editor.json`):
  three Flatpaks (the editor, titles and effects add-ons) and the GPL
  corresponding source, which `required_with` makes mandatory whenever a
  Flatpak ships. Its key is VE's export at `u-studio-video-editor@ca04cc5`
  (primary `FE210DDD…D13F`, ed25519 sign-only subkey `19157495…0813`,
  cross-certified, no expiry), published as
  `keys/u-studio-video-editor-release-FE210DDD-97ab12c5.asc` ([keys](keys/README.md)).
  Generic tests over every product config (`tests/test_products.py`); test 25
  now checks every product's pinned key against a real signature by it
  (U-Stu's signed tag `v0.80.2-beta.1`), and fails for a product without one
  ([publishing](docs/publishing.md#products)).
- First public version of the publish action and its scripts: release
  checks (names, signatures by the pinned key or its signing subkey,
  `SHA256SUMS`, the signed manifest with its zsync header, newer than
  live), the tag gate, never-overwrite uploads, release records, the
  catalog and the installers pages, verification through the CDN and the
  downstream notify ([publishing](docs/publishing.md)).
- `preflight` (with `dry-run`): the file checks only, before the tag gate,
  with no AWS or GitHub calls, to check a build on a branch before tagging.
- Deployment settings outside the repository: the role ARN from the
  caller's secret, the bucket and the distribution from an SSM parameter
  read after assuming the role (`scripts/ci-settings.sh`); locally from the
  file named by `RBA_SETTINGS`.

### Changed

- Every request `publish-release.sh` and `render-index.sh` make to the site
  (the live-manifest fetch, the length, hash, catalog and range checks)
  sends the User-Agent `rba-publish-verify/1` (`RBA_UA` in
  `scripts/lib/http.sh`), so the site's usage report counts them as our
  automation, not downloads. Tests: every curl to the site passes it, and
  the stand-in curl sees it on the wire.
- The vendored page kit is RBA Web Site's `software-kit/` at `92319bc` (19
  files, verified against Web Site's generated manifest at `53b89fa`): the
  nav is Home, Art, BucketFS, Hardware, Library, Press, Process, Software
  and Support Us. The real-kit test checks all nine links in that order.
- The vendored page kit is RBA Web Site's `software-kit/` at `2f0d60a` (19
  files, verified against Web Site's generated manifest at `7fff57e`): the
  nav is Home, then Art, Library, Press, Software and Support Us. The
  real-kit test checks all six links in that order.
- The log-masking check (test 22) treats a 12-digit account ID as a leak
  only when it stands alone, the same rule as `scan_repo.sh`. A throwaway
  key's fingerprint with 12 digits in a row failed the suite in about 1 run
  in 8. New regression test.
- The repository scan (`tests/scan_repo.sh`) reads the tested commit's
  history (`HEAD`), not every branch. Dependabot's PR branches carry
  GitHub's own committer and sign-off addresses, which failed CI for every
  push while a bot PR was open. New test 29: a bot's side branch passes,
  and the same identity on `HEAD` still fails.
- The action uses `actions/download-artifact` v8.0.2, pinned by SHA
  (`9000827…`; better retries on HTTP 429, `@actions/artifact` 6.3.1). This
  folds in Dependabot's PR #1.
- The vendored page kit is RBA Web Site's `software-kit/` at `1ee3aa0` (19
  files, verified against Web Site's generated manifest at `1ed95ee`): the
  footer's GitHub link is now the organisation,
  `github.com/orgs/Rusty-Bucket-AI-OS/`, and the real-kit test expects it.
- The vendored page kit is RBA Web Site's `software-kit/` at `695143e` (19
  files, verified against Web Site's generated manifest at `868c1ad`): the
  site's nav bar (Home, Library, Art, Support Us, Software: same-tab links,
  Software marked current) from the new `assets/nav.html`. A new real-kit
  test checks the five links, that none opens a new tab, and the current
  marker.
- The vendored page kit is RBA Web Site's `software-kit/` at `d4f050d` (18
  files, verified against Web Site's generated manifest at `cb51b94`): the
  new Rusty look. Chakra Petch replaces Anton, and one `rusty.css`
  replaces `colors.css`, `spacing.css` and `typography.css`. The footer's
  X link is now `x.com/rustybucketai`; the real-kit test checks it.
- The vendored page kit is RBA Web Site's `software-kit/` at `13071cc` (19
  files, verified against Web Site's generated manifest): U-Stu Video
  Editor's display data (tagline, pitch, its icon at 96 and 192 px) and a
  `purple` accent. The real-kit test checks that every configured product
  renders with its kit name (matching `display_name`), icon and accent.
- The vendored page kit is RBA Web Site's `software-kit/` at `0060426` (17
  files, verified against Web Site's manifest): the footer gains X and
  GitHub links with inline SVG icons (`assets/social.html`, inlined by
  `render.py`; no inline style or script, so the site's CSP is unchanged).
  The real-kit test now checks both links and that the pages link to no
  other external site.
- The pinned Rusty Wave key is RW's export at `rusty-media-player@6829e49`:
  the same primary (`E13FF843…3CEE`) and signing subkey (`2FD18486…9B84`),
  with the expiry removed from both (the user's no-expiry rule). It is
  published under the new write-once name
  `keys/rusty-wave-release-E13FF843-ec8e2d4d.asc`; the catalog's `key_url`
  follows on the next publish or `render-index` run. Signatures already
  published still verify. New test 25: publish-release.sh's own
  `verify_sig` with the real pinned key against a real RW signature (rc5's
  `SHA256SUMS`, in `tests/fixtures/`), and its tampered copy is refused;
  the key has no expiry, and its published name matches its hash.

- A failed post-publish verification no longer skips the downstream
  notify: the release is already public and its files were verified before
  upload, and the downstream verifies what it fetches. The run still fails
  ("published and notified, but verification FAILED").

### Fixed

- `publish-release.sh`, `render-index.sh` and the offline tests left a
  `/tmp/rba-*` directory per run, and the tests left a `gpg-agent` per
  throwaway keyring. Each run now removes its own scratch on exit
  (`scripts/lib/scratch.sh`: only a `/tmp/rba-<name>` it owns, not a
  symlink, real path checked first). The suite stops every keyring's agent
  from one EXIT trap. New tests: no agent and no `/tmp/rba-*` left after a
  run; the cleanup's guards (refuses `/tmp`, `/`, `$HOME`, `/tmp/rba`,
  nested paths, `..` and a symlink, all in dry-run mode). CI runs the suite
  twice and fails if anything is left. The symlink test in
  `test_release_check.py` now mocks the link instead of creating one.
- The post-publish length check used `curl -w '%header{content-length}'`,
  which needs curl 7.84; ubuntu-22.04's curl 7.81 prints it literally, so
  `v1.0.0-rc2`'s run (correctly published) failed every length check. The
  check now reads the status and `Content-Length` from `curl -I`'s headers
  (`scripts/lib/http.sh`). The run logs its curl version. Tests use a
  stand-in curl that behaves like 7.81, and CI runs on ubuntu-22.04 and
  24.04.

### Security

- The live-manifest fetch no longer treats every 403 or 404 as "nothing
  live yet". Only S3's own 403 for a missing key (`AccessDenied` XML,
  `server: AmazonS3`) counts. A CloudFront or WAF 403, a 404, a 5xx or a
  timeout (curl now has connect and total timeouts) stops the publish, so
  a blocked fetch can't skip the newer-than-live check and move `latest/`
  backwards. Offline tests (stand-in curl): S3's 403 passes; WAF 403,
  404, 503 and timeout stop; a live 200 is compared both ways; no `aws`
  or `gh` calls.

- The caller's logs may be public: the action masks the account ID, the
  role ARN, the bucket and the distribution before anything can print
  them. Offline tests run seven scenarios (preflight, dry run, SSM denied,
  a malformed parameter, a malformed role, the wrong role, an upload
  denied), apply GitHub's masking, and fail on any 12-digit number, any
  ARN with an account in it, or any deployment value; no command tracing.

