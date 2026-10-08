[rba-publish-action](../README.md) › Keys

# Release signing keys

Public keys the [publish script](../docs/publishing.md) pins. They are copied
from each product's published key and never edited. The script checks the
PRIMARY fingerprint, so a signature by a signing subkey of it is accepted.
Signatures by expired or revoked (sub)keys are refused. No pinned primary or
subkey expires (RW removed Rusty Wave's expiry after `1.0.0-rc5`). A
compromise is handled by revocation: see the maintainers' key-compromise
runbook.

| File | Product | Fingerprint | Source |
| --- | --- | --- | --- |
| `rusty-wave-release.asc` | Rusty Wave | `E13F F843 723D 5406 8E45  A3FF 54BF 2FA4 0709 3CEE` (primary, no expiry); signing subkey `2FD1 8486 57B7 06A3 5768  77E0 71DB 2DB0 49A1 9B84` (ed25519, sign-only, no expiry, cross-certified) | `unicorntearsproject/rusty-media-player` at `6829e49`, `packaging/keys/rusty-wave-release.asc` (sha256 `ec8e2d4d…`). Published as `keys/rusty-wave-release-E13FF843-ec8e2d4d.asc` (write-once); the earlier `…-3fbb82dc.asc` (with expiry) stays |
| `u-studio-video-editor-release.asc` | U-Stu Video Editor | `FE21 0DDD E210 6FDB 0C16  BFF5 D129 63B6 E6B0 D13F` (ed25519 primary, certify-only, no expiry); signing subkey `1915 7495 D0C6 700E E436  4476 570E AA94 0937 0813` (ed25519, sign-only, no expiry, cross-certified); uid `U-Stu Video Editor Release` | `unicorntearsproject/u-studio-video-editor` at `ca04cc5`, `packaging/keys/u-stu-release.asc` (sha256 `97ab12c5…`). Published as `keys/u-studio-video-editor-release-FE210DDD-97ab12c5.asc` (write-once) |

**Related:** [Publishing](../docs/publishing.md) · [README](../README.md)
