#!/usr/bin/env bash
# Publish a signed release to software.rustybucket.ai.
#
#   scripts/publish-release.sh <product> <version-or-tag> <release-dir> [--dry-run] [--preflight] [--ci]
#
# Nothing is uploaded until every check passes: names on the product's list,
# every .asc a valid signature by the pinned key, SHA256SUMS, the
# publisher's signed manifest (published unchanged, last), and a matching
# v<version> tag in the product's source repo. Versioned files are written
# with If-None-Match, so a release can never be overwritten. After a fully
# verified publish it notifies the downstream repo, if configured
# (docs/publishing.md).
#
# --preflight: the file checks only (names, signatures, SHA256SUMS, the
# manifest with its zsync header, newer than live), then stop, BEFORE the
# tag gate. No gh or aws calls; implies --dry-run. A pre-flight on a branch,
# before the tag exists; it never replaces the dry run on the tag.
# --ci: use the AWS credentials already in the environment (the GitHub OIDC
# role) instead of assuming the publish role through a local AWS profile.
# The deployment's settings (bucket, distribution, roles) come from the file
# named by RBA_SETTINGS; checks and dry runs need none (scripts/lib/settings.sh).
# --live-manifest FILE|none: compare with that manifest instead of fetching
# the live one (offline tests; render-index.sh, re-checking the version that
# IS live). --conf FILE: another product config (offline tests only).
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CHECK=(python3 "$ROOT/scripts/lib/release_check.py")
# shellcheck source-path=SCRIPTDIR source=lib/github.sh
source "$ROOT/scripts/lib/github.sh"
# shellcheck source-path=SCRIPTDIR source=lib/catalog.sh
source "$ROOT/scripts/lib/catalog.sh"
# shellcheck source-path=SCRIPTDIR source=lib/http.sh
source "$ROOT/scripts/lib/http.sh"

die() { echo "publish: $*" >&2; exit 1; }
log() { echo "publish: $*"; }
# shellcheck source-path=SCRIPTDIR source=lib/settings.sh
source "$ROOT/scripts/lib/settings.sh"
usage() { sed -n '2,24p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2; }

DRY_RUN=0
PREFLIGHT=0
CI_MODE=0
CONF=""
LIVE=""
POSITIONAL=()
while (($#)); do
  case $1 in
    --dry-run) DRY_RUN=1 ;;
    --preflight) PREFLIGHT=1 DRY_RUN=1 ;;
    --ci) CI_MODE=1 ;;
    --conf) CONF=$2; shift ;;
    --live-manifest) LIVE=$2; shift ;;
    -h|--help) usage ;;
    -*) die "unknown option $1" ;;
    *) POSITIONAL+=("$1") ;;
  esac
  shift
done
((${#POSITIONAL[@]} == 3)) || usage
PRODUCT=${POSITIONAL[0]}
[[ $PRODUCT =~ ^[a-z][a-z0-9-]*$ ]] || die "bad product name $PRODUCT"
CONF=${CONF:-$ROOT/scripts/products/$PRODUCT.json}
[[ -f $CONF ]] || die "no product config $CONF"
V=$("${CHECK[@]}" version "${POSITIONAL[1]}") || die "bad version ${POSITIONAL[1]}"
DIR=$(cd "${POSITIONAL[2]}" && pwd) || die "no release directory ${POSITIONAL[2]}"

conf() { jq -er ".$1" "$CONF"; }
[[ $(conf product) == "$PRODUCT" ]] || die "$CONF is not for $PRODUCT"
KEY_FPR=$(conf key_fingerprint)
KEY_FILE=$(conf key_file)
[[ $KEY_FILE == /* ]] || KEY_FILE=$ROOT/$KEY_FILE
MANIFEST=$(conf manifest)
PREFIX=$PRODUCT/$V

# --- 0. Tools (locally and on the CI runner) -------------------------------
tools=(gpg gpgconf jq curl openssl python3 sha256sum)
((PREFLIGHT)) || tools+=(aws gh)
for t in "${tools[@]}"; do
  command -v "$t" >/dev/null || die "missing tool: $t"
done
log "using $(curl --version | head -n 1 | cut -d' ' -f1-2)"
if ((!PREFLIGHT)); then
  aws s3api put-object --generate-cli-skeleton input 2>/dev/null | jq -e 'has("IfNoneMatch")' >/dev/null \
    || die "this AWS CLI has no put-object --if-none-match; upgrade AWS CLI v2"
fi

work=$(mktemp -d "${TMPDIR:-/tmp}/rba-XXXX")
export GNUPGHOME=$work/gnupg
mkdir -m 700 "$GNUPGHOME"
trap 'gpgconf --kill all >/dev/null 2>&1 || true' EXIT

# --- 1. Names ---------------------------------------------------------------
names=$("${CHECK[@]}" names --conf "$CONF" --dir "$DIR" --version "$V") \
  || die "file names don't match the $PRODUCT list"
mapfile -t FILES <<<"$names"
log "names ok: ${#FILES[@]} versioned files + manifest pair"

# --- 2. Signatures (throwaway keyring, pinned fingerprint) ------------------
gpg --batch --quiet --import "$KEY_FILE" 2>/dev/null || die "can't import $KEY_FILE"
fpr=$(gpg --batch --with-colons --list-keys | awk -F: '$1 == "fpr" { print $10; exit }')
[[ $fpr == "$KEY_FPR" ]] || die "$KEY_FILE is $fpr, config pins $KEY_FPR"
verify_sig() {
  # Exactly one signature; GOODSIG (gpg's "good, by a key that is neither
  # expired nor revoked": an expired or revoked (sub)key gives EXPKEYSIG /
  # REVKEYSIG yet still a VALIDSIG); and VALIDSIG's last field, the PRIMARY
  # key's fingerprint, is the pinned one, so a signing subkey of it is fine.
  # (The same rule as RBA Wave's scripts/lib/sig.sh: gpg exits 0, exactly
  # one signature and one GOODSIG, and none of the bad statuses below.)
  local status rc=0
  status=$(gpg --batch --status-fd 1 --verify "$1.asc" "$1" 2>/dev/null) || rc=$?
  [[ $(grep -c '^\[GNUPG:\] NEWSIG' <<<"$status") == 1 ]] \
    || die "$(basename "$1").asc must hold exactly one signature"
  if ((rc != 0)) || [[ $(grep -c '^\[GNUPG:\] GOODSIG ' <<<"$status") != 1 ]] \
     || grep -qE '^\[GNUPG:\] (BADSIG|ERRSIG|EXPSIG|EXPKEYSIG|REVKEYSIG|NO_PUBKEY|FAILURE)( |$)' <<<"$status"; then
    die "no good signature on $(basename "$1") (bad, or by an expired or revoked key)"
  fi
  [[ $(awk '$2 == "VALIDSIG" { print $NF }' <<<"$status") == "$KEY_FPR" ]] \
    || die "no valid signature by $KEY_FPR on $(basename "$1")"
}
for f in "${FILES[@]}" "$MANIFEST"; do
  [[ $f == *.asc ]] && continue
  verify_sig "$DIR/$f"
done
log "signatures ok ($KEY_FPR)"

# --- 3. Checksums and manifest ----------------------------------------------
"${CHECK[@]}" checksums --conf "$CONF" --dir "$DIR" --version "$V" || die "checksums failed"
live_args=()
if [[ $LIVE == none ]]; then
  :
elif [[ -n $LIVE ]]; then
  live_args=(--live "$LIVE")
else
  # Only S3's own answer for a missing key (the bucket is private, so a 403
  # with its AccessDenied XML) means "nothing live yet". Anything else (a
  # CDN or WAF block, a 5xx, a timeout) stops, so the newer-than-live check
  # is never skipped.
  code=$(curl -sS --connect-timeout 20 --max-time 120 -D "$work/live.h" -o "$work/live.json" -w '%{http_code}' \
    "$BASE_URL/$PRODUCT/latest/$MANIFEST") || die "can't fetch the live manifest (network error or timeout)"
  case $code in
    200) live_args=(--live "$work/live.json") ;;
    403)
      if grep -qiE '^server: *AmazonS3[[:space:]]*$' "$work/live.h" && grep -q '<Code>AccessDenied</Code>' "$work/live.json"; then
        log "no live manifest yet (first publish)"
      else
        die "live manifest answered HTTP 403, but not S3's (a CDN or WAF block?): stopping rather than skip the newer-than-live check"
      fi ;;
    *) die "live manifest answered HTTP $code: stopping rather than skip the newer-than-live check" ;;
  esac
fi
"${CHECK[@]}" manifest --conf "$CONF" --dir "$DIR" --version "$V" --base-url "$BASE_URL" "${live_args[@]}" \
  || die "manifest check failed"
log "checksums and manifest ok: $PRODUCT $V"
if ((PREFLIGHT)); then
  log "preflight only: file checks passed; the tag gate, the bucket checks and the upload were NOT run"
  exit 0
fi

# --- 3b. Only tagged versions publish: v<version> must exist in the source
# repo, and any commit the release names must be the tag's commit. Fails
# closed; there is no skip.
SOURCE_REPO=$(conf source_repo)
TAG=v$V
TAG_COMMIT=$(resolve_tag_commit "$SOURCE_REPO" "$TAG") || die "only tagged versions publish: $TAG not confirmed in $SOURCE_REPO"
named=$("${CHECK[@]}" commits --conf "$CONF" --dir "$DIR" --version "$V") || die "can't read the commits the release names"
while IFS=$'\t' read -r source sha; do
  [[ -z $source ]] && continue
  [[ $sha == "$TAG_COMMIT" ]] || die "$source names commit $sha, but $TAG is $TAG_COMMIT"
done <<<"$named"
log "tag ok: $SOURCE_REPO $TAG = $TAG_COMMIT"

name_of() { "${CHECK[@]}" name --conf "$CONF" --version "$V" --id "$1"; }
declare -A ALIAS=()
while IFS=$'\t' read -r pid alias; do
  ALIAS[$(name_of "$pid")]=$alias
done < <(jq -r '.aliases | to_entries[] | "\(.key)\t\(.value)"' "$CONF")

ctype() { "${CHECK[@]}" content-type "$1"; }
b64sha() { openssl dgst -sha256 -binary "$1" | base64; }
SUMS=$(name_of "$(conf checksums_file)")

if ((DRY_RUN)); then
  log "dry run: would upload with If-None-Match, Cache-Control immutable:"
  for f in "${FILES[@]}"; do echo "  PUT  $PREFIX/$f  [$(ctype "$f")]"; done
  log "dry run: would replace in $PRODUCT/latest/ (max-age=60):"
  for src in "${!ALIAS[@]}"; do
    [[ -f $DIR/$src ]] || continue
    echo "  PUT  $PRODUCT/latest/${ALIAS[$src]}  (+ .asc) from $src"
  done
  echo "  PUT  $PRODUCT/latest/$MANIFEST.asc"
  echo "  PUT  $PRODUCT/latest/$MANIFEST  (last, unchanged)"
  log "dry run: then index pages, invalidate /* on the distribution, verify via $BASE_URL"
  echo "  PUT  $PREFIX/release.json  (If-None-Match: the release record)"
  echo "  PUT  $(conf key_url_path)  (If-None-Match, once)"
  echo "  PUT  $CATALOG_KEY  (rebuilt from every release record, max-age=60)"
  echo "  PUT  _kit/*  (page kit assets, If-None-Match), then the installers pages"
  if jq -e .notify "$CONF" >/dev/null; then
    log "dry run: then start $(conf notify.workflow) on $(conf notify.repo)@$(conf notify.ref) (version $V, tag $TAG)"
  fi
  exit 0
fi

# --- 4. Credentials: the publish role, for this process only --------------
need_settings BUCKET DISTRIBUTION_ID
if ((CI_MODE)); then
  need_settings CI_ROLE_NAME
  # The CI job assumed the OIDC role already; make sure that's what we have.
  [[ -n ${AWS_ACCESS_KEY_ID:-} ]] || die "--ci: no AWS credentials in the environment"
  unset AWS_PROFILE
  arn=$(aws sts get-caller-identity --region "$REGION" --query Arn --output text) || die "--ci: credentials don't work"
  [[ $arn == *":assumed-role/$CI_ROLE_NAME/"* ]] || die "--ci: running as $arn, expected role $CI_ROLE_NAME"
else
  need_settings AWS_PROFILE_NAME PUBLISH_ROLE_ARN
  creds=$(aws sts assume-role --profile "$AWS_PROFILE_NAME" --region "$REGION" \
    --role-arn "$PUBLISH_ROLE_ARN" --role-session-name "publish-$PRODUCT-$V" \
    --query Credentials --output json) || die "can't assume $PUBLISH_ROLE_ARN"
  AWS_ACCESS_KEY_ID=$(jq -r .AccessKeyId <<<"$creds")
  AWS_SECRET_ACCESS_KEY=$(jq -r .SecretAccessKey <<<"$creds")
  AWS_SESSION_TOKEN=$(jq -r .SessionToken <<<"$creds")
  export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
  unset AWS_PROFILE creds
fi
s3() { aws s3api "$@" --bucket "$BUCKET" --region "$REGION"; }

# put_once <file> <key> <content-type> <cache-control>: create a key that
# must never change. An identical existing object is fine (an interrupted
# earlier run); a different one aborts.
put_once() {
  local out have
  if out=$(s3 put-object --key "$2" --body "$1" --if-none-match '*' --checksum-sha256 "$(b64sha "$1")" \
      --content-type "$3" --cache-control "$4" 2>&1); then
    log "created $2"
  elif grep -q PreconditionFailed <<<"$out"; then
    have=$(s3 head-object --key "$2" --checksum-mode ENABLED --query ChecksumSHA256 --output text) \
      || die "$2 exists but can't be read back"
    [[ $have == "$(b64sha "$1")" ]] || die "$2 already exists with different content"
    log "already there, identical: $2"
  else
    die "upload of $2 failed: $out"
  fi
}

# --- 4b. Every version already in the bucket has its release record, or the
# catalog couldn't be rebuilt after this publish. Checked before anything
# changes (docs/publishing.md).
aws s3api list-objects-v2 --bucket "$BUCKET" --region "$REGION" --query Contents --output json >"$work/pre.json" \
  || die "can't list the bucket"
missing=$(versions_without_records "$work/pre.json" "$PRODUCT" "$V")
[[ -z $missing ]] || die "no release record for $PRODUCT $missing: run scripts/render-index.sh first"

# --- 5. Upload versioned files (never overwrite) ----------------------------
for f in "${FILES[@]}"; do
  key=$PREFIX/$f
  if out=$(s3 put-object --key "$key" --body "$DIR/$f" --if-none-match '*' \
      --checksum-sha256 "$(b64sha "$DIR/$f")" --content-type "$(ctype "$f")" \
      --cache-control 'public, max-age=31536000, immutable' 2>&1); then
    log "uploaded $key"
  elif grep -q PreconditionFailed <<<"$out"; then
    # Already there (an interrupted earlier run): fine only if identical.
    have=$(s3 head-object --key "$key" --checksum-mode ENABLED --query ChecksumSHA256 --output text) \
      || die "$key exists but can't be read back"
    [[ $have == "$(b64sha "$DIR/$f")" ]] || die "$key already exists with different content"
    log "already published, identical: $key"
  else
    die "upload of $key failed: $out"
  fi
done

# --- 6. Every manifest file is in the bucket with its size and SHA-256 ------
while IFS=$'\t' read -r name size sha; do
  read -r have_size have_sha < <(s3 head-object --key "$PREFIX/$name" --checksum-mode ENABLED \
    --query '[ContentLength, ChecksumSHA256]' --output text)
  [[ $have_size == "$size" ]] || die "$PREFIX/$name is $have_size bytes, manifest says $size"
  [[ $have_sha == "$("${CHECK[@]}" hex2b64 "$sha")" ]] || die "$PREFIX/$name SHA-256 differs from the manifest"
done < <("${CHECK[@]}" manifest-files --manifest "$DIR/$MANIFEST")
log "bucket matches the manifest"

# --- 6b. The release record (immutable) and the public key (once) ----------
python3 "$ROOT/scripts/lib/catalog.py" record --conf "$CONF" --version "$V" --manifest "$DIR/$MANIFEST" \
  --commit "$TAG_COMMIT" --base-url "$BASE_URL" >"$work/release.json" || die "can't build the release record"
put_once "$work/release.json" "$PREFIX/release.json" 'application/json' 'public, max-age=31536000, immutable'
put_once "$KEY_FILE" "$(conf key_url_path)" 'application/pgp-keys' 'public, max-age=31536000, immutable'

# --- 7. Aliases, then 8. the manifest (last), unchanged ---------------------
put_latest() {
  # With its SHA-256 stored: the catalog matches aliases to versions by it.
  s3 put-object --key "$PRODUCT/latest/$2" --body "$1" --content-type "$(ctype "$2")" \
    --checksum-sha256 "$(b64sha "$1")" --cache-control 'public, max-age=60' >/dev/null \
    || die "can't write $PRODUCT/latest/$2"
  log "replaced $PRODUCT/latest/$2"
}
for src in "${!ALIAS[@]}"; do
  [[ -f $DIR/$src ]] || continue
  put_latest "$DIR/$src" "${ALIAS[$src]}"
  put_latest "$DIR/$src.asc" "${ALIAS[$src]}.asc"
done
put_latest "$DIR/$MANIFEST.asc" "$MANIFEST.asc"
put_latest "$DIR/$MANIFEST" "$MANIFEST"

# --- 8b. The catalog, rebuilt from every release record ---------------------
publish_catalog

# --- Installers pages (the page kit) and invalidation -----------------------
render_site "$work/catalog.json"
inv=$(aws cloudfront create-invalidation --region "$REGION" --distribution-id "$DISTRIBUTION_ID" \
  --paths '/*' --query Invalidation.Id --output text) || die "invalidation failed"
aws cloudfront wait invalidation-completed --region "$REGION" --distribution-id "$DISTRIBUTION_ID" \
  --id "$inv" || die "invalidation $inv didn't complete"
log "invalidated /* ($inv)"

# --- 9. Verify through the public URL ---------------------------------------
fail=0
bad() { log "FAIL $*"; fail=1; }
same_sha() { [[ $(curl -sS "$1" | sha256sum | cut -d' ' -f1) == "$(sha256sum <"$2" | cut -d' ' -f1)" ]]; }
same_sha "$BASE_URL/$PRODUCT/latest/$MANIFEST" "$DIR/$MANIFEST" || bad "live manifest differs from $MANIFEST"
live_latest=$(curl -sS "$BASE_URL/$CATALOG_KEY" | jq -r --arg p "$PRODUCT" '.products[] | select(.id == $p) | .latest_version') \
  || live_latest=""
[[ $live_latest == "$V" ]] || bad "catalog says $PRODUCT latest is '${live_latest}', want $V"
same_sha "$BASE_URL/$(conf key_url_path)" "$KEY_FILE" || bad "published key differs from $KEY_FILE"
while IFS=$'\t' read -r name size _; do
  for url in "$BASE_URL/$PREFIX/$name" "$BASE_URL/$PREFIX/$name.asc"; do
    out=$(head_status_length "$url") || out="no-answer -"
    read -r code len <<<"$out"
    [[ $code == 200 ]] || bad "$url: HTTP $code"
    [[ $url == *.asc || $len == "$size" ]] || bad "$url: length $len, want $size"
  done
done < <("${CHECK[@]}" manifest-files --manifest "$DIR/$MANIFEST")
for src in "${!ALIAS[@]}"; do
  [[ -f $DIR/$src ]] || continue
  same_sha "$BASE_URL/$PRODUCT/latest/${ALIAS[$src]}" "$DIR/$src" || bad "alias ${ALIAS[$src]} differs from $src"
done

# Range requests (zsync). Multi-range first, while this edge is still cold:
# a 200 there is reported (S3 can't do multi-range); on a warm edge it fails.
zs_target=$(jq -r '.zsync.target // empty' "$CONF")
target=${zs_target:+$(name_of "$zs_target")}
if [[ -n $target && -f $DIR/$target ]]; then
  url=$BASE_URL/$PREFIX/$target
  range_check() {
    curl -sS -D "$work/h" -o "$work/b" -H "Range: bytes=$1" "$url"
    "${CHECK[@]}" ranges --file "$DIR/$target" --headers "$work/h" --body "$work/b" --ranges "$1"
  }
  if out=$(range_check 0-1023,4096-8191 2>&1); then log "multi-range, cold edge: $out"
  else log "WARN multi-range, cold edge: $out"; fi
  if out=$(range_check 0-1023,4096-8191 2>&1); then log "multi-range, warm edge: $out"
  else bad "multi-range, warm edge: $out"; fi
  if out=$(range_check 100-199 2>&1); then log "single range: $out"
  else bad "single range: $out"; fi
fi

# The never-overwrite rule, live, on the smallest versioned file. Both
# writes must be refused; they send identical bytes, so even a broken
# policy couldn't change any content.
probe=$PREFIX/$SUMS
if s3 put-object --key "$probe" --body "$DIR/$SUMS" --if-none-match '*' >/dev/null 2>"$work/e"; then
  bad "If-None-Match put of existing $probe succeeded"
elif grep -q PreconditionFailed "$work/e"; then log "existing key, If-None-Match put: refused (412)"
else bad "If-None-Match probe: $(cat "$work/e")"; fi
if s3 put-object --key "$probe" --body "$DIR/$SUMS" >/dev/null 2>"$work/e"; then
  bad "unconditional overwrite of $probe succeeded"
elif grep -q AccessDenied "$work/e"; then log "unconditional overwrite: refused (AccessDenied)"
else bad "overwrite probe: $(cat "$work/e")"; fi
# (No delete probe: this role has no s3:DeleteObject, so IAM would refuse it
# before the bucket policy is consulted. The bucket policy's delete deny is
# tested separately, by the site's maintainers.)

if ((fail == 0)); then
  log "done: $PRODUCT $V published and verified at $BASE_URL/$PREFIX/"
else
  log "WARN $PRODUCT $V IS published (manifest and aliases live), but verification FAILED (see above)"
fi

# --- 10. Notify downstream (never fails the publish: it's already out) ------
# Also after a failed verification: the release is already public, its files
# were verified before upload and in the bucket, and the downstream verifies
# what it fetches itself. The run still fails below, so a person looks.
if jq -e .notify "$CONF" >/dev/null; then
  notify_published "$(conf notify.repo)" "$(conf notify.workflow)" "$(conf notify.ref)" "$V"
fi
((fail == 0)) || die "published and notified, but verification FAILED (see above)"
echo "CHANGELOG: $(date -u +%F) published $PRODUCT $V to $BASE_URL/$PREFIX/ (${#FILES[@]} files), manifest and aliases updated, verified"
