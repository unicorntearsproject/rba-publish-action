[rba-publish-action](../README.md) › Keys

# Release signing keys

Public keys the [publish script](../docs/publishing.md) pins. They are copied
from each product's published key and never edited. The script checks the
PRIMARY fingerprint, so a signature by a signing subkey of it is accepted.
Signatures by expired or revoked (sub)keys are refused. The primary expires
on 2028-10-04 and must be extended before then.

| File | Product | Fingerprint | Source |
| --- | --- | --- | --- |
| `rusty-wave-release.asc` | Rusty Wave | `E13F F843 723D 5406 8E45  A3FF 54BF 2FA4 0709 3CEE` (primary); signing subkey `2FD1 8486 57B7 06A3 5768  77E0 71DB 2DB0 49A1 9B84` (ed25519, expires 2028-10-06, cross-certified) | `unicorntearsproject/rusty-media-player` at `74f463f`, `packaging/keys/rusty-wave-release.asc`. Published as `keys/rusty-wave-release-E13FF843-3fbb82dc.asc` (write-once) |

**Related:** [Publishing](../docs/publishing.md) · [README](../README.md)
