#!/usr/bin/env bash
# Offline test of scripts/publish-release.sh (no AWS, no network): a fake
# release signed by a throwaway key, run with --dry-run against a test
# config that pins that key. Run: tests/test_publish_offline.sh
# shellcheck disable=SC2030,SC2031  # subshells deliberately isolate each test's environment
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
work=$(mktemp -d /tmp/rba-XXXX)
export GNUPGHOME=$work/gnupg
mkdir -m 700 "$GNUPGHOME"
trap 'gpgconf --kill all >/dev/null 2>&1 || true' EXIT

# A stand-in gh answers the tag lookups and dispatches (tests/fake-gh/gh).
export PATH="$ROOT/tests/fake-gh:$PATH"
export FAKE_GH_LOG=$work/gh.log FAKE_GH_SHA=d5f5935dc3a28d249baeae6236b345dc3b07f3b5
export FAKE_GH_TAG=lightweight FAKE_GH_DISPATCH=ok

pass=0 failed=0
# A stand-in deployment for render-index (publish checks and dry runs need none).
cat >"$work/settings.env" <<EOF
BUCKET=test-bucket
DISTRIBUTION_ID=ETESTDIST
AWS_PROFILE_NAME=test-profile
PUBLISH_ROLE_ARN=test-role
EOF
KEYPATH=$(jq -r .key_url_path "$ROOT/scripts/products/rusty-wave.json")
ok() { echo "ok   $1"; pass=$((pass + 1)); }
nok() { echo "FAIL $1"; failed=$((failed + 1)); }
expect() { # pattern label: the last run's output must contain pattern
  if grep -q "$1" "$work/out"; then ok "$2"; else nok "$2"; cat "$work/out"; fi
}

# Throwaway signing key and a test product config pinning it.
gpg --batch --quiet --passphrase '' --quick-gen-key 'Publish Test <test@invalid>' ed25519 sign never 2>/dev/null
FPR=$(gpg --batch --with-colons --list-keys | awk -F: '$1 == "fpr" { print $10; exit }')
gpg --batch --armor --export "$FPR" >"$work/test-key.asc"
jq --arg k "$work/test-key.asc" --arg f "$FPR" '.key_file = $k | .key_fingerprint = $f' \
  "$ROOT/scripts/products/rusty-wave.json" >"$work/conf.json"

make_release() { # dir version [build-info JSON]
  mkdir -p "$1"
  PYTHONPATH="$ROOT/tests:$ROOT/scripts/lib" python3 -c "
import json, test_release_check as t, release_check as rc
t.CONF = rc.load_conf('$work/conf.json')
t.make_release('$1', v='$2', build_info=json.loads('${3:-null}'))
"
  # Real detached signatures over every non-.asc file.
  for f in "$1"/*; do
    [[ $f == *.asc ]] && continue
    rm -f "$f.asc"
    gpg --batch --quiet --armor --detach-sign --local-user "$FPR" -o "$f.asc" "$f"
  done
}

run() { # dir version [extra args...]: run the dry run, capture output
  "$ROOT/scripts/publish-release.sh" rusty-wave "$2" "$1" --dry-run --conf "$work/conf.json" \
    --live-manifest "${3:-none}" >"$work/out" 2>&1
}

# 1. A good release passes and plans the right writes.
make_release "$work/good" 0.0.5
if run "$work/good" v0.0.5 && grep -q 'PUT  rusty-wave/0.0.5/rusty-wave_0.0.5_amd64.deb' "$work/out" \
  && grep -q 'rusty-wave/latest/rusty-wave-latest-x86_64.AppImage.zsync' "$work/out" \
  && grep -q 'rusty-wave-latest.json  (last, unchanged)' "$work/out"; then
  ok "good release: dry run plans versioned uploads, aliases, manifest last"
else nok "good release"; cat "$work/out"; fi

# 2. A newer live manifest blocks the publish.
echo '{"version": "0.0.6"}' >"$work/live.json"
if run "$work/good" 0.0.5 "$work/live.json"; then nok "older than live accepted"; else
  expect 'not newer' "version not newer than live: refused"
fi

# 3. A file changed after signing: the signature check fails first.
cp -r "$work/good" "$work/tampered"
printf 'x' >>"$work/tampered/rusty-wave_0.0.5_amd64.deb"
if run "$work/tampered" 0.0.5; then nok "tampered file accepted"; else
  expect 'no good signature' "tampered file: signature refused"
fi

# 4. A signature by another key is refused.
cp -r "$work/good" "$work/otherkey"
GNUPGHOME=$work/gnupg2 bash -c '
  mkdir -m 700 "$GNUPGHOME"
  gpg --batch --quiet --passphrase "" --quick-gen-key "Other <o@invalid>" ed25519 sign never 2>/dev/null
  rm -f "$1.asc"; gpg --batch --quiet --armor --detach-sign -o "$1.asc" "$1"
  gpgconf --kill all' _ "$work/otherkey/rusty-wave-web-0.0.5.zip"
if run "$work/otherkey" 0.0.5; then nok "foreign signature accepted"; else
  expect 'no good signature' "signature by another key: refused"
fi

# 5. A stray file is refused before any signature check.
cp -r "$work/good" "$work/stray"
echo hi >"$work/stray/index.html"; cp "$work/stray/index.html" "$work/stray/index.html.asc"
if run "$work/stray" 0.0.5; then nok "stray file accepted"; else
  expect 'not on the' "stray index.html: refused"
fi

# 6. The wrong version for the files is refused.
if run "$work/good" 0.0.6; then nok "wrong version accepted"; else ok "wrong version: refused"; fi

# 7. Tag gate: annotated tags are dereferenced to their commit.
export FAKE_GH_TAG=annotated
if run "$work/good" 0.0.5; then expect "tag ok: unicorntearsproject/rusty-media-player v0.0.5 = $FAKE_GH_SHA" "annotated tag: dereferenced to its commit"
else nok "annotated tag refused"; cat "$work/out"; fi

# 8. Tag gate: a missing tag aborts before anything else happens.
export FAKE_GH_TAG=missing
if run "$work/good" 0.0.5; then nok "missing tag accepted"; else
  expect "tag v0.0.5 doesn't exist in unicorntearsproject/rusty-media-player" "missing tag: refused"
  if grep -q 'PUT' "$work/out"; then nok "missing tag: still planned uploads"; else ok "missing tag: nothing planned"; fi
fi

# 9. Tag gate: an unreachable API fails closed.
export FAKE_GH_TAG=error
if run "$work/good" 0.0.5; then nok "API failure accepted"; else
  expect "can't read tag v0.0.5" "API failure: refused (fail closed)"
fi
export FAKE_GH_TAG=lightweight

# 10. build-info.json naming another commit is refused; the right one passes.
make_release "$work/wrongcommit" 0.0.5 '{"version": "0.0.5", "commit": "6e2566503ca56bf8c2393553a3ddbaa1195d8cc4"}'
if run "$work/wrongcommit" 0.0.5; then nok "wrong build-info commit accepted"; else
  expect "names commit 6e2566503ca56bf8c2393553a3ddbaa1195d8cc4, but v0.0.5 is $FAKE_GH_SHA" "build-info commit differs from tag: refused"
fi
make_release "$work/rightcommit" 0.0.5 "{\"version\": \"0.0.5\", \"commit\": \"$FAKE_GH_SHA\"}"
if run "$work/rightcommit" 0.0.5; then ok "build-info commit equals tag: accepted"; else nok "matching build-info commit refused"; cat "$work/out"; fi

# 11. CI: the source token reaches gh as GH_TOKEN; locally gh uses its own auth.
: >"$FAKE_GH_LOG"
PUBLISH_SOURCE_TOKEN=test-token run "$work/good" 0.0.5 || true
if grep -q 'git/ref/tags/v0.0.5 .*token=set' "$FAKE_GH_LOG"; then ok "CI source token passed to gh"; else nok "CI source token not used"; fi
: >"$FAKE_GH_LOG"
(unset GH_TOKEN; run "$work/good" 0.0.5) || true
if grep -q 'git/ref/tags/v0.0.5 .*token=$' "$FAKE_GH_LOG"; then ok "local: gh uses its own auth"; else nok "local run set a token"; cat "$FAKE_GH_LOG"; fi

# 12. Notify: workflow_dispatch with ref, version and tag (never dry_run),
# with the dispatch token; a failure never fails the publish.
notify() { # mode: run notify_published, capture output and status
  : >"$FAKE_GH_LOG"
  (unset GH_TOKEN; FAKE_GH_DISPATCH=$1 PUBLISH_DISPATCH_TOKEN=pat \
    bash -c 'source "$0/scripts/lib/github.sh"; notify_published unicorntearsproject/rba-app-rusty-wave deploy-wave.yml main 0.0.5' "$ROOT") \
    >"$work/out" 2>&1
}
want='gh api -X POST repos/unicorntearsproject/rba-app-rusty-wave/actions/workflows/deploy-wave.yml/dispatches -f ref=main -f inputs[version]=0.0.5 -f inputs[tag]=v0.0.5 | token=set'
if notify ok && grep -q 'started deploy-wave.yml on unicorntearsproject/rba-app-rusty-wave@main' "$work/out" \
  && grep -qxF "$want" "$FAKE_GH_LOG"; then
  ok "notify: workflow_dispatch with ref, version, tag and the dispatch token"
else nok "notify call"; cat "$work/out" "$FAKE_GH_LOG"; fi
if grep -q dry_run "$FAKE_GH_LOG"; then nok "notify sent dry_run"; else ok "notify: never sends dry_run"; fi
if notify fail; then
  expect 'WARN the release IS published' "notify failure: loud warning, exit 0"
  expect "gh api -X POST repos/unicorntearsproject/rba-app-rusty-wave/actions/workflows/deploy-wave.yml/dispatches -f ref=main -f 'inputs\[version\]=0.0.5' -f 'inputs\[tag\]=v0.0.5'" "notify failure: prints the exact retry command"
else nok "notify failure returned non-zero"; fi

# 13. The dry run shows the deploy it would start.
if run "$work/good" 0.0.5; then expect 'then start deploy-wave.yml on unicorntearsproject/rba-app-rusty-wave@main (version 0.0.5, tag v0.0.5)' "dry run: plans the Wave deploy"
else nok "dry run failed"; cat "$work/out"; fi

# 14. Pre-releases: 1.0.0-rc1 over a live 0.0.4 plans the exact names and
# paths, moves latest/, and starts the Wave deploy; under a live 1.0.0 it's
# refused (downgrade).
make_release "$work/rc1" 1.0.0-rc1
echo '{"version": "0.0.4"}' >"$work/live-old.json"
if run "$work/rc1" v1.0.0-rc1 "$work/live-old.json"; then
  expect 'PUT  rusty-wave/1.0.0-rc1/rusty-wave_1.0.0~rc1_amd64.deb' "rc: Debian name under rusty-wave/1.0.0-rc1/"
  expect 'PUT  rusty-wave/1.0.0-rc1/rusty-wave-1.0.0-0.1.rc1.x86_64.rpm' "rc: RPM name (Fedora pre-release release)"
  expect 'rusty-wave/latest/rusty-wave-latest-x86_64.AppImage  (+ .asc) from rusty-wave-1.0.0-rc1-x86_64.AppImage' "rc: latest/ moves for a pre-release"
  expect 'tag ok: unicorntearsproject/rusty-media-player v1.0.0-rc1' "rc: tag gate checks v1.0.0-rc1"
  expect 'PUT  rusty-wave/1.0.0-rc1/release.json  (If-None-Match' "rc: plans the immutable release record"
  expect "PUT  $KEYPATH  (If-None-Match, once)" "rc: plans the key, once"
  expect 'PUT  catalog/latest/catalog.json' "rc: plans the catalog"
  expect '(version 1.0.0-rc1, tag v1.0.0-rc1)' "rc: Wave deploy gets version and tag"
else nok "rc release refused"; cat "$work/out"; fi
echo '{"version": "1.0.0"}' >"$work/live-final.json"
if run "$work/rc1" 1.0.0-rc1 "$work/live-final.json"; then nok "rc over live 1.0.0 accepted"; else
  expect 'not newer' "rc under a live final: refused (downgrade)"
fi

# 15. render-index, against a fake bucket (tests/fake-aws): 0.0.5 has its
# record; 1.0.0-rc1 is live but has none (published before records existed).
bucket=$work/bucket
mkdir -p "$work/products" "$bucket/rusty-wave/0.0.5" "$bucket/rusty-wave/1.0.0-rc1" "$bucket/rusty-wave/latest"
cp "$work/conf.json" "$work/products/rusty-wave.json"
make_release "$work/r005" 0.0.5
make_release "$work/r100" 1.0.0-rc1
for v in 0.0.5:r005 1.0.0-rc1:r100; do
  ver=${v%%:*} src=$work/${v##*:}
  for f in "$src"/*; do
    case ${f##*/} in rusty-wave-latest.json*) continue ;; esac
    cp "$f" "$bucket/rusty-wave/$ver/"
  done
done
python3 "$ROOT/scripts/lib/catalog.py" record --conf "$work/conf.json" --version 0.0.5 \
  --manifest "$work/r005/rusty-wave-latest.json" --commit "$FAKE_GH_SHA" --base-url https://software.rustybucket.ai \
  >"$bucket/rusty-wave/0.0.5/release.json"
cp "$work/r100/rusty-wave-latest.json" "$work/r100/rusty-wave-latest.json.asc" "$bucket/rusty-wave/latest/"
cp "$work/r100/rusty-wave-1.0.0-rc1-x86_64.AppImage" "$bucket/rusty-wave/latest/rusty-wave-latest-x86_64.AppImage"
cp "$work/r100/rusty-wave-1.0.0-rc1-x86_64.AppImage.zsync" "$bucket/rusty-wave/latest/rusty-wave-latest-x86_64.AppImage.zsync"
render() { # args: run render-index against the fake bucket
  FAKE_S3_DIR=$bucket FAKE_AWS_LOG=$work/aws.log PATH="$ROOT/tests/fake-aws:$PATH" RBA_SETTINGS=$work/settings.env \
    "$ROOT/scripts/render-index.sh" --products-dir "$work/products" "$@" >"$work/out" 2>&1
}
if render --dry-run; then
  expect 'BACKFILL: rusty-wave 1.0.0-rc1 has no release record' "render-index: finds the live version without a record"
  expect "would create rusty-wave/1.0.0-rc1/release.json (checks passed, tag commit $FAKE_GH_SHA)" "render-index: backfill passes the full publish checks"
  # (The tool preflight's --generate-cli-skeleton probe writes nothing.)
  if [[ -e $bucket/rusty-wave/1.0.0-rc1/release.json ]] \
    || grep 'put-object' "$work/aws.log" | grep -qv -- '--generate-cli-skeleton'; then nok "dry run wrote to the bucket"
  else ok "render-index --dry-run: writes nothing"; fi
else nok "render-index dry run failed"; cat "$work/out"; fi

# A record-less version that isn't the live one can't be backfilled.
mkdir -p "$bucket/rusty-wave/0.0.6"; cp "$bucket/rusty-wave/0.0.5/rusty-wave-web-0.0.5.zip" "$bucket/rusty-wave/0.0.6/x"
if render --dry-run; then nok "non-live version backfilled"; else
  expect "rusty-wave 0.0.6 has no release record and isn't the live version (1.0.0-rc1)" "render-index: refuses a non-live version without a record"
fi
mv "$bucket/rusty-wave/0.0.6/x" "$work/x-moved"; rmdir "$bucket/rusty-wave/0.0.6"

# A file changed in the bucket fails the backfill's checks.
cp "$bucket/rusty-wave/1.0.0-rc1/rusty-wave-web-1.0.0-rc1.zip" "$work/web-orig"
printf 'x' >>"$bucket/rusty-wave/1.0.0-rc1/rusty-wave-web-1.0.0-rc1.zip"
if render --dry-run; then nok "tampered bucket file backfilled"; else
  expect "rusty-wave 1.0.0-rc1 failed the publish checks" "render-index: a tampered file fails the backfill"
fi
cp "$work/web-orig" "$bucket/rusty-wave/1.0.0-rc1/rusty-wave-web-1.0.0-rc1.zip"

# publish_catalog against the fake bucket, once rc1 has its record.
python3 "$ROOT/scripts/lib/catalog.py" record --conf "$work/conf.json" --version 1.0.0-rc1 \
  --manifest "$work/r100/rusty-wave-latest.json" --commit "$FAKE_GH_SHA" --base-url https://software.rustybucket.ai \
  >"$bucket/rusty-wave/1.0.0-rc1/release.json"
if (export FAKE_S3_DIR=$bucket PATH="$ROOT/tests/fake-aws:$PATH" PRODUCTS=$work/products
    BUCKET=test-bucket REGION=us-east-1 BASE_URL=https://software.rustybucket.ai
    die() { echo "die: $*" >&2; exit 1; }; log() { echo "log: $*"; }
    source "$ROOT/scripts/lib/catalog.sh"; publish_catalog) >"$work/out" 2>&1; then
  c=$bucket/catalog/latest/catalog.json
  if jq -e '.schema == 1 and .products[0].latest_version == "1.0.0-rc1"
      and ([.products[0].versions[].version] == ["1.0.0-rc1", "0.0.5"])
      and .products[0].latest["linux-appimage"].version == "1.0.0-rc1"
      and (.products[0].latest | has("linux-appimage-zsync") | not)
      and .products[0].key_url == "https://software.rustybucket.ai/\($k)"' --arg k "$KEYPATH" "$c" >/dev/null; then
    ok "publish_catalog: catalog from the bucket (order, latest, aliases, key_url)"
  else nok "catalog content"; jq . "$c" | sed -n "1,30p"; fi
else nok "publish_catalog failed"; cat "$work/out"; fi

# 16. render_site with a stand-in page kit (tests/fake-kit), against the
# fake bucket that now holds both records and the catalog.
render_site_run() {
  (export FAKE_S3_DIR=$bucket PATH="$ROOT/tests/fake-aws:$PATH" PRODUCTS=$work/products KIT_DIR=$ROOT/tests/fake-kit
   BUCKET=test-bucket REGION=us-east-1 BASE_URL=https://software.rustybucket.ai
   die() { echo "die: $*" >&2; exit 1; }; log() { echo "log: $*"; }
   source "$ROOT/scripts/lib/catalog.sh"; render_site "$bucket/catalog/latest/catalog.json") >"$work/out" 2>&1
}
if render_site_run; then
  if [[ -f $bucket/_kit/kit.0123456789.css && -f $bucket/_kit/space-grotesk-400.abcdef0123.woff2 \
     && -f $bucket/index.html && -f $bucket/rusty-wave/index.html ]]; then ok "render_site: kit assets and kit pages uploaded"
  else nok "render_site uploads"; find "$bucket" -maxdepth 2 | sort; fi
  folder=$bucket/rusty-wave/1.0.0-rc1/index.html
  if grep -q '<link rel="stylesheet" href="/_kit/kit.0123456789.css">' "$folder" && ! grep -q '<style>' "$folder"; then
    ok "render_site: folder pages link the kit CSS, no inline style"
  else nok "folder page styling"; head -12 "$folder"; fi
  [[ -f $bucket/rusty-wave/latest/index.html && ! -e $bucket/rusty-wave/index.html.folder ]] && ok "render_site: latest/ folder page written"
else nok "render_site failed"; cat "$work/out"; fi
if render_site_run; then ok "render_site: a second identical render is fine"; else nok "repeat render failed"; cat "$work/out"; fi
if FAKE_KIT_CSS='body{color:red}' render_site_run; then nok "changed kit asset overwritten"; else
  expect '_kit/kit.0123456789.css already exists with different content' "render_site: a fingerprinted asset never changes"
fi
before=$(find "$bucket" -type f | wc -l)
if FAKE_KIT_REFUSE=1 render_site_run; then nok "refused catalog rendered"; else
  expect 'the page kit refused the catalog' "render_site: a kit refusal stops it"
  [[ $(find "$bucket" -type f | wc -l) == "$before" ]] && ok "render_site: a refusal writes nothing"
fi

# 17. render_site with the REAL vendored page kit (vendor/software-kit).
real=$(mktemp -d "$work/realkit-XXXX")
cp -r "$bucket/rusty-wave" "$bucket/catalog" "$real/"
if (export FAKE_S3_DIR=$real PATH="$ROOT/tests/fake-aws:$PATH" PRODUCTS=$work/products
    BUCKET=test-bucket REGION=us-east-1 BASE_URL=https://software.rustybucket.ai
    die() { echo "die: $*" >&2; exit 1; }; log() { echo "log: $*"; }
    source "$ROOT/scripts/lib/catalog.sh"; render_site "$real/catalog/latest/catalog.json") >"$work/out" 2>&1; then
  css=$(cd "$real" && find _kit -name 'kit.*.css')
  if [[ -n $css && -f $real/index.html && -f $real/rusty-wave/index.html ]] \
     && grep -q "href=\"/$css\"" "$real/rusty-wave/1.0.0-rc1/index.html" \
     && ! grep -lq -e '<style' -e '<script' -e ' style=' "$real/index.html" "$real/rusty-wave/index.html"; then
    ok "real kit: pages, fingerprinted assets, folder pages on its CSS, no inline style or script"
  else nok "real kit render"; (cd "$real" && find . -type f | sort | sed -n "1,30p"); fi
else nok "real kit render_site failed"; cat "$work/out"; fi

# 18. With every record present, the render-index dry run passes, plans the
# missing public key and renders with the real kit (nothing written).
if render --dry-run; then
  expect "would publish $KEYPATH" "render-index: plans the missing public key"
  expect 'dry run: the page kit renders it (2 pages)' "render-index --dry-run: the real kit renders the catalog"
else nok "render-index dry run failed"; cat "$work/out"; fi

# 19. An empty bucket (nothing published yet): render-index succeeds, writes
# the catalog with no products and the key, and renders no pages.
empty=$(mktemp -d "$work/empty-XXXX")
render_empty() {
  FAKE_S3_DIR=$empty FAKE_AWS_LOG=$work/aws-empty.log PATH="$ROOT/tests/fake-aws:$PATH" RBA_SETTINGS=$work/settings.env \
    "$ROOT/scripts/render-index.sh" --products-dir "$work/products" "$@" >"$work/out" 2>&1
}
if render_empty --dry-run; then
  expect 'dry run: no published versions yet, the pages would not be rendered' "empty bucket: dry run succeeds, no render"
else nok "empty-bucket dry run failed"; cat "$work/out"; fi
# The real run stops only at the final CDN check (no network in tests);
# everything before it must have happened.
render_empty || true
if grep -q 'pages: no published versions yet, nothing to render' "$work/out" \
   && jq -e '.schema == 1 and .products == []' "$empty/catalog/latest/catalog.json" >/dev/null \
   && [[ -f $empty/$KEYPATH ]] \
   && [[ -z $(find "$empty" -name index.html) && ! -d $empty/_kit ]]; then
  ok "empty bucket: catalog (no products) and key written, no pages, no kit assets"
else nok "empty-bucket render"; cat "$work/out"; find "$empty" -type f; fi

# 20. Signing SUBKEYS of the pinned primary (RW's CI signs with one): a good
# subkey passes; an expired or revoked subkey, or two signatures, fail.
sub_home=$work/subkeys
mkdir -m 700 "$sub_home"
subgpg() { GNUPGHOME=$sub_home gpg --batch --quiet --pinentry-mode loopback --passphrase '' "$@" 2>/dev/null; }
subgpg --quick-gen-key 'Sub Test <s@invalid>' ed25519 cert never
PFPR=$(GNUPGHOME=$sub_home gpg --with-colons -k | awk -F: '$1 == "fpr" { print $10; exit }')
newsub() { # usage: newsub <expire>; prints the new subkey's fingerprint
  subgpg --quick-add-key "$PFPR" ed25519 sign "$1"
  GNUPGHOME=$sub_home gpg --with-colons -k | awk -F: '$1 == "fpr" { f = $10 } END { print f }'
}
sign_release() { # usage: sign_release <dir> <subkey fpr>: re-sign every file with that subkey
  for f in "$1"/*; do
    [[ $f == *.asc ]] && continue
    rm -f "$f.asc"
    subgpg --armor --detach-sign --local-user "$2!" -o "$f.asc" "$f"
  done
}
subconf() { # a config pinning the PRIMARY, exported with its current subkey state
  GNUPGHOME=$sub_home gpg --batch --armor --export "$PFPR" >"$work/sub-key.asc"
  jq --arg k "$work/sub-key.asc" --arg f "$PFPR" '.key_file = $k | .key_fingerprint = $f' \
    "$ROOT/scripts/products/rusty-wave.json" >"$work/sub-conf.json"
}
subrun() { "$ROOT/scripts/publish-release.sh" rusty-wave 0.0.5 "$1" --dry-run --conf "$work/sub-conf.json" --live-manifest none >"$work/out" 2>&1; }

GOOD_SUB=$(newsub never)
make_release "$work/subgood" 0.0.5
# The manifest names the key it's signed with: the pinned PRIMARY.
jq --arg f "$PFPR" '.key_fingerprint = $f' "$work/subgood/rusty-wave-latest.json" >"$work/m.json"
mv "$work/m.json" "$work/subgood/rusty-wave-latest.json"
sign_release "$work/subgood" "$GOOD_SUB"
subconf
if subrun "$work/subgood"; then expect "signatures ok ($PFPR)" "subkey signature of the pinned primary: accepted"
else nok "subkey-signed release refused"; cat "$work/out"; fi

EXP_SUB=$(newsub seconds=2)
cp -r "$work/subgood" "$work/subexp"; sign_release "$work/subexp" "$EXP_SUB"
sleep 3
subconf
if subrun "$work/subexp"; then nok "expired subkey accepted"; else
  expect 'no good signature' "expired signing subkey: refused"
fi

REV_SUB=$(newsub never)
cp -r "$work/subgood" "$work/subrev"; sign_release "$work/subrev" "$REV_SUB"
printf 'key %s\nrevkey\ny\n0\n\ny\nsave\n' "$REV_SUB" | GNUPGHOME=$sub_home gpg --batch --pinentry-mode loopback \
  --passphrase '' --command-fd 0 --edit-key "$PFPR" >/dev/null 2>&1
subconf
if GNUPGHOME=$sub_home gpg --with-colons -k | awk -F: -v s="$REV_SUB" '$1 == "sub" { v = $2 } $1 == "fpr" && $10 == s { print v }' | grep -q r; then
  if subrun "$work/subrev"; then nok "revoked subkey accepted"; else
    expect 'no good signature' "revoked signing subkey: refused"
  fi
else nok "test setup: the subkey wasn't revoked"; fi

cp -r "$work/subgood" "$work/subtwo"
f=$work/subtwo/rusty-wave-web-0.0.5.zip
subgpg --armor --detach-sign --local-user "$GOOD_SUB!" -o "$f.asc2" "$f"
cat "$f.asc2" >>"$f.asc"; rm -f "$f.asc2"
if subrun "$work/subtwo"; then nok "two signatures accepted"; else
  expect 'must hold exactly one signature' "two signatures in one .asc: refused"
fi

# A good signature plus one by a foreign key, in one .asc: refused.
foreign_home=$work/foreign
mkdir -m 700 "$foreign_home"
GNUPGHOME=$foreign_home gpg --batch --quiet --pinentry-mode loopback --passphrase '' \
  --quick-gen-key 'Foreign <f@invalid>' ed25519 sign never 2>/dev/null
cp -r "$work/subgood" "$work/subforeign"
f=$work/subforeign/rusty-wave-web-0.0.5.zip
GNUPGHOME=$foreign_home gpg --batch --quiet --pinentry-mode loopback --passphrase '' \
  --armor --detach-sign -o "$f.foreign" "$f" 2>/dev/null
cat "$f.foreign" >>"$f.asc"; rm -f "$f.foreign"
if subrun "$work/subforeign"; then nok "good + foreign signatures accepted"; else
  expect 'must hold exactly one signature' "good + foreign signature in one .asc: refused"
fi

# The PRIMARY key itself (no subkey) still signs acceptably: the original
# fixtures in test 1 are signed that way and pass.

# 21. --preflight (RW's branch pre-flight, before the tag exists): the file
# checks only, then a "preflight only" stop BEFORE the tag gate. aws and gh
# are replaced by tripwires that log any call; preflight must make none.
mkdir -p "$work/tripwire"
for t in aws gh; do
  printf '#!/usr/bin/env bash\necho "%s $*" >>"%s"\nexit 99\n' "$t" "$work/tripwire.log" >"$work/tripwire/$t"
  chmod +x "$work/tripwire/$t"
done
: >"$work/tripwire.log"
preflight() { # dir version [live]: preflight with the tripwires first on PATH
  PATH="$work/tripwire:$PATH" "$ROOT/scripts/publish-release.sh" rusty-wave "$2" "$1" --preflight \
    --conf "$work/conf.json" --live-manifest "${3:-none}" --ci >"$work/out" 2>&1
}
if preflight "$work/good" v0.0.5; then
  expect 'checksums and manifest ok: rusty-wave 0.0.5' "preflight: the file checks ran"
  expect 'preflight only: file checks passed; the tag gate, the bucket checks and the upload were NOT run' \
    "preflight: says explicitly what it did NOT run"
  if grep -qE 'tag ok|PUT ' "$work/out"; then nok "preflight: reached the tag gate or the plan"; cat "$work/out"
  else ok "preflight: stops before the tag gate and the plan"; fi
else nok "preflight: good release refused"; cat "$work/out"; fi
if [[ -s $work/tripwire.log ]]; then nok "preflight: called aws or gh"; cat "$work/tripwire.log"
else ok "preflight: no aws or gh calls (good release)"; fi
if preflight "$work/tampered" 0.0.5; then nok "preflight: tampered file accepted"; else
  expect 'no good signature' "preflight: tampered file refused"
fi
if preflight "$work/otherkey" 0.0.5; then nok "preflight: foreign signature accepted"; else
  expect 'no good signature' "preflight: signature by another key refused"
fi
if preflight "$work/stray" 0.0.5; then nok "preflight: stray file accepted"; else
  expect 'not on the' "preflight: stray file refused"
fi
if preflight "$work/good" 0.0.5 "$work/live.json"; then nok "preflight: older than live accepted"; else
  expect 'not newer' "preflight: version not newer than live refused"
fi
cp -r "$work/good" "$work/badsums"
sums=$(find "$work/badsums" -name '*SHA256SUMS' | head -n 1)
sed -i '1s/^[0-9a-f]\{8\}/00000000/' "$sums"
gpg --batch --quiet --yes --armor --detach-sign --local-user "$FPR" -o "$sums.asc" "$sums"
if preflight "$work/badsums" 0.0.5; then nok "preflight: wrong SHA256SUMS accepted"; else
  expect 'checksums failed' "preflight: wrong SHA256SUMS (validly signed) refused"
fi
if [[ -s $work/tripwire.log ]]; then nok "preflight: called aws or gh"; cat "$work/tripwire.log"
else ok "preflight: no aws or gh calls (refusals)"; fi
# Without --preflight, the dry run still runs the tag gate, fail closed.
export FAKE_GH_TAG=missing
if run "$work/good" 0.0.5; then nok "dry run without preflight skipped the tag gate"; else
  expect "tag v0.0.5 doesn't exist" "dry run without --preflight: tag gate still runs (missing tag refused)"
fi
export FAKE_GH_TAG=lightweight

# 22. The caller's logs are public. Each scenario runs the action's steps as
# GitHub would (ci-settings.sh mask, then read, then publish-release.sh),
# applies GitHub's masking to the combined log (every ::add-mask:: value
# becomes *** from then on), and greps what's left: no 12-digit number, no
# ARN with an account in it, none of the deployment's values. The values are
# sentinels here; a private checkout can pass its real ones (MASK_ACCOUNT,
# MASK_BUCKET, MASK_DIST, MASK_FORBIDDEN_FILE: extra fixed strings).
acct=${MASK_ACCOUNT:-$(printf '%04d' 4242 4242 4242)}
mbucket=${MASK_BUCKET:-sentinel-bucket-7f3a}
mdist=${MASK_DIST:-ESENTINEL7F3A}
role_arn="arn:aws:iam::$acct:role/test-publish-gha"
caller="arn:aws:sts::$acct:assumed-role/test-publish-gha/publish-rusty-wave-1"
printf '%s\n' "$acct" "$mbucket" "$mdist" >"$work/forbidden"
[[ -n ${MASK_FORBIDDEN_FILE:-} ]] && cat "$MASK_FORBIDDEN_FILE" >>"$work/forbidden"
github_log() { # stdin: a job's raw output -> stdout: what GitHub would show
  python3 -c '
import sys
masks = []
for line in sys.stdin:
    line = line.rstrip("\n")
    if line.startswith("::add-mask::"):
        if line[12:]:
            masks.append(line[12:])
        continue
    for m in sorted(masks, key=len, reverse=True):
        line = line.replace(m, "***")
    print(line)'
}
leaks() { # log: print each forbidden thing found
  grep -nE '(^|[^0-9])[0-9]{12}([^0-9]|$)' "$1" || true
  grep -nE 'arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:[0-9]' "$1" || true
  grep -nFf "$work/forbidden" "$1" || true
}
job() { # name, then the job's commands as a function: run, mask, check
  local name=$1; shift
  (export FAKE_S3_DIR=$work/mask-bucket FAKE_ACCOUNT=$acct FAKE_BUCKET=$mbucket FAKE_CALLER_ARN=$caller
   export PATH="$ROOT/tests/fake-aws:$PATH" RUNNER_TEMP=$work/runner AWS_ACCESS_KEY_ID=AKIAFAKE
   mkdir -p "$FAKE_S3_DIR" "$RUNNER_TEMP"; "$@") >"$work/raw-$name.log" 2>&1 || true
  github_log <"$work/raw-$name.log" >"$work/log-$name.log"
  if [[ -n $(leaks "$work/log-$name.log") ]]; then
    nok "masking: $name leaks"; leaks "$work/log-$name.log"
  else ok "masking: $name: nothing identifying in the log"; fi
}
mask_step() { ROLE_ARN=$1 "$ROOT/scripts/ci-settings.sh" mask; }
read_step() { ROLE_ARN=$role_arn SETTINGS_PARAMETER=/test/settings "$ROOT/scripts/ci-settings.sh" read "$RUNNER_TEMP/s.env"; }
publish_step() { RBA_SETTINGS=${1:-} "$ROOT/scripts/publish-release.sh" rusty-wave 0.0.5 "$work/good" --ci \
  --conf "$work/conf.json" --live-manifest none "${@:2}"; }
good_ssm=$(jq -cn --arg b "$mbucket" --arg d "$mdist" '{bucket: $b, distribution_id: $d}')

j_preflight() { mask_step ""; publish_step "" --dry-run --preflight; }
j_dryrun() { mask_step "$role_arn"; publish_step "" --dry-run; }
j_ssm_denied() { mask_step "$role_arn"; FAKE_SSM=denied read_step; }
j_ssm_bad() { mask_step "$role_arn"; FAKE_SSM_VALUE="{\"bucket\": \"NOT A BUCKET $mbucket\", \"distribution_id\": \"$mdist\"}" read_step; }
j_bad_role() { mask_step "arn:aws:iam::$acct:user/someone"; }
j_wrong_role() { mask_step "$role_arn"; FAKE_SSM_VALUE=$good_ssm read_step
  FAKE_CALLER_ARN="arn:aws:sts::$acct:assumed-role/other-role/x" publish_step "$RUNNER_TEMP/s.env"; }
j_put_denied() { mask_step "$role_arn"; FAKE_SSM_VALUE=$good_ssm read_step; FAKE_PUT=denied publish_step "$RUNNER_TEMP/s.env"; }
for j in preflight dryrun ssm_denied ssm_bad bad_role wrong_role put_denied; do job "$j" "j_$j"; done
# Each scenario got as far as it should (so the checks above mean something).
if grep -q 'preflight only' "$work/log-preflight.log" && grep -q 'PUT  rusty-wave/0.0.5/' "$work/log-dryrun.log" \
  && grep -q 'not authorized to perform: ssm:GetParameter' "$work/log-ssm_denied.log" \
  && grep -q "bucket isn't a bucket name" "$work/log-ssm_bad.log" \
  && grep -q "isn't an IAM role ARN" "$work/log-bad_role.log" \
  && grep -q 'running as arn:aws:sts::\*\*\*:assumed-role/other-role' "$work/log-wrong_role.log" \
  && grep -q 'not authorized to perform: s3:PutObject on resource: arn:aws:s3:::\*\*\*/rusty-wave/0.0.5/' "$work/log-put_denied.log"; then
  ok "masking: every scenario reached its identifying output, masked"
else nok "masking: a scenario didn't reach its point"; tail -n 5 "$work"/log-*.log; fi
# The settings file is written only from validated values, and is safe to source.
(export PATH="$ROOT/tests/fake-aws:$PATH" RUNNER_TEMP=$work/runner FAKE_SSM_VALUE=$good_ssm FAKE_S3_DIR=$work/mask-bucket
 read_step) >/dev/null 2>&1 || true
if [[ $(source "$work/runner/s.env"; echo "$BUCKET $DISTRIBUTION_ID $CI_ROLE_NAME") == "$mbucket $mdist test-publish-gha" ]]; then
  ok "settings: the file carries the bucket, the distribution and the role name"
else nok "settings: wrong settings file"; cat "$work/runner/s.env"; fi
# A real publish without settings stops before any AWS call.
: >"$work/aws-nosettings.log"
if FAKE_AWS_LOG=$work/aws-nosettings.log FAKE_S3_DIR=$work/mask-bucket PATH="$ROOT/tests/fake-aws:$PATH" AWS_ACCESS_KEY_ID=AKIAFAKE \
    "$ROOT/scripts/publish-release.sh" rusty-wave 0.0.5 "$work/good" --ci --conf "$work/conf.json" --live-manifest none >"$work/out" 2>&1; then
  nok "publish without settings accepted"
else
  expect 'BUCKET is not set' "publish without RBA_SETTINGS: refused"
  if grep -qv 'generate-cli-skeleton' "$work/aws-nosettings.log"; then nok "publish without settings: called AWS"
  else ok "publish without settings: no AWS call"; fi
fi
# The action: the mask step comes first; the OIDC step masks the account ID;
# settings are read after the OIDC step; nothing traces commands.
names=$(grep -E '^    - name: ' "$ROOT/action.yml" | sed 's/^    - name: //')
if [[ $(head -n 1 <<<"$names") == 'Mask the role and the account ID' ]] \
   && grep -q '^        mask-aws-account-id: true$' "$ROOT/action.yml" \
   && (( $(grep -n 'Assume the publish role' <<<"$names" | cut -d: -f1) < $(grep -n 'Read the deployment settings' <<<"$names" | cut -d: -f1) )); then
  ok "action: masks first, OIDC masks the account ID, settings read after the role"
else nok "action: step order or OIDC masking"; echo "$names"; fi
if grep -rnE 'set -[a-z]*x|xtrace|BASH_XTRACEFD' "$ROOT/scripts" "$ROOT/action.yml" >"$work/out"; then
  nok "no command tracing in the publish path"; cat "$work/out"
else ok "no command tracing (set -x) in the publish path"; fi

# 23. The live manifest fetch: only S3's own 403 (AccessDenied XML, server
# AmazonS3: the key doesn't exist in the private bucket) means "nothing live
# yet". A CloudFront/WAF 403, a 404, a 5xx or a timeout stops, so the
# newer-than-live check can never be skipped. Runs the real fetch through a
# stand-in curl (tests/fake-curl), in preflight (no aws or gh: tripwires).
live_run() { # mode [body]: preflight of the good 0.0.5 release against that answer
  : >"$work/tripwire.log"
  FAKE_CURL=$1 FAKE_CURL_BODY=${2:-} PATH="$work/tripwire:$ROOT/tests/fake-curl:$PATH" \
    "$ROOT/scripts/publish-release.sh" rusty-wave 0.0.5 "$work/good" --preflight --conf "$work/conf.json" >"$work/out" 2>&1
}
if live_run s3-403; then expect 'no live manifest yet (first publish)' "live: S3's AccessDenied 403 = nothing live yet"
else nok "live: S3's 403 refused"; cat "$work/out"; fi
if live_run waf-403; then nok "live: a CloudFront/WAF 403 accepted as nothing live"; else
  expect "answered HTTP 403, but not S3's" "live: a CloudFront/WAF 403 stops the publish"
fi
if live_run s3-404; then nok "live: a 404 accepted"; else expect 'answered HTTP 404' "live: a 404 stops the publish"; fi
if live_run 503; then nok "live: a 503 accepted"; else expect 'answered HTTP 503' "live: a 5xx stops the publish"; fi
if live_run timeout; then nok "live: a timeout accepted"; else
  expect "can't fetch the live manifest (network error or timeout)" "live: a timeout stops the publish"
fi
echo '{"version": "0.0.4"}' >"$work/live-old.json"
if live_run ok "$work/live-old.json"; then expect 'checksums and manifest ok: rusty-wave 0.0.5' "live: 200 with an older version: compared, passes"
else nok "live: newer than an older live refused"; cat "$work/out"; fi
if live_run ok "$work/live.json"; then nok "live: older than live accepted via the fetch"; else
  expect 'not newer' "live: 200 with a newer version: refused"
fi
if [[ -s $work/tripwire.log ]]; then nok "live: aws or gh called"; cat "$work/tripwire.log"
else ok "live: no aws or gh calls"; fi

echo "publish offline: $pass passed, $failed failed"
((failed == 0))
