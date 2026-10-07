# rba-publish-action

A GitHub Action, and the scripts behind it, that verify a signed, tagged
release and publish it to [software.rustybucket.ai](https://software.rustybucket.ai/),
the download site for Rusty Bucket's software (Rusty Wave first). Nothing is
uploaded until every check has passed, and a published version can never
be overwritten.

- [Docs](docs/README.md): [publishing](docs/publishing.md),
  [catalog schema](docs/catalog.md)
- [Keys](keys/README.md), the pinned release keys
- [Vendored page kit](vendor/README.md)
- [Changelog](CHANGELOG.md)

## Use

The calling job runs on a `v*` tag push, declares **no** `environment:`, and
pins this action by commit SHA (never a branch or tag):

```yaml
on:
  push:
    tags: ["v*"]
jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      id-token: write   # GitHub OIDC, for the publish role
      contents: read    # read this repo's tags for the tag gate
    steps:
      # … build, sign, then put the release files in dist/ (or upload an artifact)
      - uses: unicorntearsproject/rba-publish-action@<approved commit SHA>
        with:
          tag: ${{ github.ref_name }}
          release-dir: dist                                # or: artifact-name: <name>
          role-arn: ${{ secrets.RBA_PUBLISH_ROLE_ARN }}    # a secret, never a literal
          dispatch-token: ${{ secrets.RBA_WAVE_DISPATCH_TOKEN }}
          # dry-run: "true"     # every check, write nothing, no role needed
          # preflight: "true"   # with dry-run, on a branch: file checks only
```

| Input | Default | What |
| --- | --- | --- |
| `tag` | (required) | `v<semver>`; must exist in the product's source repo |
| `product` | `rusty-wave` | A config in [`scripts/products/`](scripts/products/) |
| `release-dir` / `artifact-name` | | Exactly one: where the release files are |
| `role-arn` | | The publish role, from a secret; not needed for a dry run |
| `settings-parameter` | `/rusty-bucket/publish/settings` | SSM parameter with the bucket and distribution |
| `source-token` | `github.token` | Reads the source repo's tags |
| `dispatch-token` | | Starts the downstream deploy workflow, if the product has one |
| `dry-run` | `false` | `true`: every check and the plan, nothing written, no AWS |
| `preflight` | `false` | With `dry-run`: the file checks only, before the tag gate |

## Trust model

- **What the caller can do** is limited by the AWS role, not by this code:
  the role trusts only GitHub OIDC tokens for one repository's `v*` tags,
  can create objects but never overwrite or delete published ones (the
  bucket refuses it), and can invalidate the CDN.
- **What runs** is this repository at the SHA the caller pins. Each pinned
  commit is reviewed and approved by the site's maintainers before callers
  move to it. The action prints the SHA-256 of every script it runs.
- **What's verified** before any upload: names, a detached signature by the
  pinned key (or its signing subkey) on every file, `SHA256SUMS`, the
  signed manifest, newer than live, and the tag: `v<version>` must exist
  and any commit the build names must be the tag's commit.
- **Nothing deployment-specific is in this repository.** The role ARN comes
  from the caller's secret; the bucket and the distribution come from an
  SSM parameter only the role can read. Callers' logs may be public, so the
  action masks the account ID, the role ARN, the bucket and the
  distribution before anything can print them, and nothing traces commands.
- **This repository** is on GitHub Free: branch protection and environment
  restrictions aren't available, so callers pin full commit SHAs and
  approval happens on the SHA, not on a branch.

## Develop

```bash
tests/test_publish_offline.sh                              # the scripts, offline (fake aws and gh)
python3 -m unittest discover -s tests -p 'test_*.py'       # release checks and catalog
tests/scan_repo.sh                                         # nothing identifying or secret in the repo
```

The offline tests need `bash`, `gpg`, `jq`, `openssl` and `python3`.
CI runs all three on every push and pull request, with no secrets.

## Licence

Dual-licensed under [MIT](LICENSE-MIT) OR [Apache-2.0](LICENSE-APACHE), at
your option. The vendored fonts are under the SIL Open Font License (texts
in [`vendor/software-kit/assets/`](vendor/software-kit/assets/)).
