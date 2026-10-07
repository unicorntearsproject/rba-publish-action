# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Callers pin commit SHAs; each entry names what changed for them.

## [Unreleased]

### Added

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

