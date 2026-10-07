# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Callers pin commit SHAs; each entry names what changed for them.

## [Unreleased]

### Security

- The live-manifest fetch no longer treats every 403 or 404 as "nothing
  live yet". Only S3's own 403 for a missing key (`AccessDenied` XML,
  `server: AmazonS3`) counts. A CloudFront or WAF 403, a 404, a 5xx or a
  timeout (curl now has connect and total timeouts) stops the publish, so
  a blocked fetch can't skip the newer-than-live check and move `latest/`
  backwards. Offline tests (stand-in curl): S3's 403 passes; WAF 403,
  404, 503 and timeout stop; a live 200 is compared both ways; no `aws`
  or `gh` calls.

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

### Security

- The caller's logs may be public: the action masks the account ID, the
  role ARN, the bucket and the distribution before anything can print
  them. Offline tests run seven scenarios (preflight, dry run, SSM denied,
  a malformed parameter, a malformed role, the wrong role, an upload
  denied), apply GitHub's masking, and fail on any 12-digit number, any
  ARN with an account in it, or any deployment value; no command tracing.
