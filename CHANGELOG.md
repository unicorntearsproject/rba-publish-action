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

### Security

- The caller's logs may be public: the action masks the account ID, the
  role ARN, the bucket and the distribution before anything can print
  them. Offline tests run seven scenarios (preflight, dry run, SSM denied,
  a malformed parameter, a malformed role, the wrong role, an upload
  denied), apply GitHub's masking, and fail on any 12-digit number, any
  ARN with an account in it, or any deployment value; no command tracing.
