[rba-publish-action](../README.md) › Vendor

# Vendored code

| Path | What | Source | Pinned by |
| --- | --- | --- | --- |
| `software-kit/` | The page kit for `software.rustybucket.ai` (`render.py`, CSS, fonts, icons, the nav bar, the footer's X and GitHub links, the Corporate mode switch and theme with its one first-party script `mode.js`, each product's source link, licences; Rusty Wave and U-Stu Video Editor display data), by RBA Web Site, which owns it | RBA Web Site's `software-kit/` at `d09e872` (26 files; manifest at website-primary `943b44f`) | `software-kit.sha256`, Web Site's generated vendoring manifest |

Never edit these files. Changes come as a new kit commit from RBA Web Site.
They are re-vendored, re-verified (`cd vendor && sha256sum -c software-kit.sha256`)
and approved with the publish set. `render_site` refuses to run a kit that
doesn't match the manifest. The fonts are under the SIL Open Font License,
with the licence texts beside them in `software-kit/assets/`.

**Related:** [Catalog](../docs/catalog.md) · [README](../README.md)
