[rba-publish-action](../README.md) › Vendor

# Vendored code

| Path | What | Source | Pinned by |
| --- | --- | --- | --- |
| `software-kit/` | The page kit for `software.rustybucket.ai` (`render.py`, CSS, fonts, icons, licences), by RBA Web Site, which owns it | RBA Web Site's `software-kit/` at `39729e4859d734a2ade96d47d2cd89f7b700f068` | `software-kit.sha256`, Web Site's generated vendoring manifest |

Never edit these files. Changes come as a new kit commit from RBA Web Site.
They are re-vendored, re-verified (`cd vendor && sha256sum -c software-kit.sha256`)
and approved with the publish set. `render_site` refuses to run a kit that
doesn't match the manifest. The fonts are under the SIL Open Font License,
with the licence texts beside them in `software-kit/assets/`.

**Related:** [Catalog](../docs/catalog.md) · [README](../README.md)
