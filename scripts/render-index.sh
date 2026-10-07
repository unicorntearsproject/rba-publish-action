#!/usr/bin/env bash
# Re-render software.rustybucket.ai from the live bucket, without
# publishing anything new (docs/publishing.md).
#
#   scripts/render-index.sh [--dry-run] [--ci]
#
# 1. Backfill: a version folder without a release record gets one only if it
#    is the version the live signed manifest names (the latest), after the
#    full publish checks (publish-release.sh --dry-run on its files, fetched
#    from the bucket). Any other version without a record stops the render.
# 2. Rebuilds catalog/latest/catalog.json from every release record, writes
#    the index pages, invalidates /* and checks the catalog through the CDN.
#
# --dry-run: report what would be backfilled and check the catalog builds,
# but write nothing. --ci: use the AWS credentials already in the
# environment (as publish-release.sh --ci). --products-dir DIR: other
# product configs (offline tests only). Always needs RBA_SETTINGS (the
# bucket and distribution; scripts/lib/settings.sh).
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source-path=SCRIPTDIR source=lib/catalog.sh
source "$ROOT/scripts/lib/catalog.sh"
# shellcheck source-path=SCRIPTDIR source=lib/scratch.sh
source "$ROOT/scripts/lib/scratch.sh"
# shellcheck source-path=SCRIPTDIR source=lib/http.sh
source "$ROOT/scripts/lib/http.sh"

die() { echo "render-index: $*" >&2; exit 1; }
log() { echo "render-index: $*"; }
# shellcheck source-path=SCRIPTDIR source=lib/settings.sh
source "$ROOT/scripts/lib/settings.sh"
usage() { sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2; }

DRY_RUN=0
CI_MODE=0
PRODUCTS=$ROOT/scripts/products
while (($#)); do
  case $1 in
    --dry-run) DRY_RUN=1 ;;
    --ci) CI_MODE=1 ;;
    --products-dir) PRODUCTS=$2; shift ;;
    -h|--help) usage ;;
    *) die "unknown argument $1" ;;
  esac
  shift
done
ci_args=()
((CI_MODE)) && ci_args=(--ci)
need_settings BUCKET DISTRIBUTION_ID

for t in aws jq curl openssl python3; do
  command -v "$t" >/dev/null || die "missing tool: $t"
done
work=$(mktemp -d "${TMPDIR:-/tmp}/rba-XXXX")
trap 'scratch_cleanup "$work"' EXIT   # this run's scratch only (lib/scratch.sh)

# Credentials: the publish role, for this process only (as publish-release.sh).
if ((CI_MODE)); then
  need_settings CI_ROLE_NAME
  [[ -n ${AWS_ACCESS_KEY_ID:-} ]] || die "--ci: no AWS credentials in the environment"
  unset AWS_PROFILE
  arn=$(aws sts get-caller-identity --region "$REGION" --query Arn --output text) || die "--ci: credentials don't work"
  [[ $arn == *":assumed-role/$CI_ROLE_NAME/"* ]] || die "--ci: running as $arn, expected role $CI_ROLE_NAME"
else
  need_settings AWS_PROFILE_NAME PUBLISH_ROLE_ARN
  creds=$(aws sts assume-role --profile "$AWS_PROFILE_NAME" --region "$REGION" \
    --role-arn "$PUBLISH_ROLE_ARN" --role-session-name render-index \
    --query Credentials --output json) || die "can't assume $PUBLISH_ROLE_ARN"
  AWS_ACCESS_KEY_ID=$(jq -r .AccessKeyId <<<"$creds")
  AWS_SECRET_ACCESS_KEY=$(jq -r .SecretAccessKey <<<"$creds")
  AWS_SESSION_TOKEN=$(jq -r .SessionToken <<<"$creds")
  export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
  unset AWS_PROFILE creds
fi
s3() { aws s3api "$@" --bucket "$BUCKET" --region "$REGION"; }

# --- 1. Backfill missing release records -------------------------------------
s3 list-objects-v2 --query Contents --output json >"$work/listing.json" || die "can't list the bucket"
for conf in "$PRODUCTS"/*.json; do
  product=$(jq -r .product "$conf")
  manifest=$(jq -r .manifest "$conf")
  missing=$(versions_without_records "$work/listing.json" "$product")
  [[ -n $missing ]] || continue
  live=$(s3 get-object --key "$product/latest/$manifest" "$work/$product-live.json" >/dev/null \
    && jq -r .version "$work/$product-live.json") || die "$product: can't read the live manifest"
  for v in $missing; do
    [[ $v == "$live" ]] || die "$product $v has no release record and isn't the live version ($live): it can't be backfilled"
    log "=================================================================="
    log "BACKFILL: $product $v has no release record; checking it like a publish"
    log "=================================================================="
    dir=$work/$product-$v
    mkdir -p "$dir"
    while read -r key; do
      s3 get-object --key "$key" "$dir/${key##*/}" >/dev/null || die "can't fetch $key"
    done < <(jq -r --arg p "$product/$v/" '.[]? | .Key | select(startswith($p) and (endswith("/index.html") | not))' "$work/listing.json")
    cp -- "$work/$product-live.json" "$dir/$manifest"
    s3 get-object --key "$product/latest/$manifest.asc" "$dir/$manifest.asc" >/dev/null || die "can't fetch $manifest.asc"
    # The same checks as a publish: names, signatures, SHA256SUMS, the
    # manifest against the files, the tag gate and the commits. Writes nothing.
    "$ROOT/scripts/publish-release.sh" "$product" "$v" "$dir" --dry-run --live-manifest none --conf "$conf" "${ci_args[@]}" \
      >"$work/check-$v.log" 2>&1 || { cat "$work/check-$v.log" >&2; die "$product $v failed the publish checks"; }
    commit=$(sed -n 's/^publish: tag ok: .* = \([0-9a-f]\{40\}\)$/\1/p' "$work/check-$v.log")
    [[ $commit =~ ^[0-9a-f]{40}$ ]] || die "$product $v: no tag commit in the check output"
    python3 "$ROOT/scripts/lib/catalog.py" record --conf "$conf" --version "$v" --manifest "$dir/$manifest" \
      --commit "$commit" --base-url "$BASE_URL" >"$work/release-$v.json" || die "can't build the record for $v"
    if ((DRY_RUN)); then
      log "dry run: would create $product/$v/release.json (checks passed, tag commit $commit)"
      continue
    fi
    s3 put-object --key "$product/$v/release.json" --body "$work/release-$v.json" --if-none-match '*' \
      --checksum-sha256 "$(openssl dgst -sha256 -binary "$work/release-$v.json" | base64)" \
      --content-type application/json --cache-control 'public, max-age=31536000, immutable' >/dev/null \
      || die "can't create $product/$v/release.json"
    log "BACKFILL: created $product/$v/release.json (tag commit $commit)"
  done
done

# --- 1b. Each product's public key, once (If-None-Match; the catalog links it)
for conf in "$PRODUCTS"/*.json; do
  key=$(jq -r '.key_url_path // empty' "$conf")
  [[ -n $key ]] || continue
  file=$(jq -r .key_file "$conf")
  [[ $file == /* ]] || file=$ROOT/$file
  want=$(openssl dgst -sha256 -binary "$file" | base64)
  if jq -e --arg k "$key" 'any(.[]?; .Key == $k)' "$work/listing.json" >/dev/null; then
    have=$(s3 head-object --key "$key" --checksum-mode ENABLED --query ChecksumSHA256 --output text) \
      || die "can't read $key"
    [[ $have == "$want" ]] || die "$key exists with different content than $file"
  elif ((DRY_RUN)); then
    log "dry run: would publish $key"
  else
    s3 put-object --key "$key" --body "$file" --if-none-match '*' --checksum-sha256 "$want" \
      --content-type application/pgp-keys --cache-control 'public, max-age=31536000, immutable' >/dev/null \
      || die "can't create $key"
    log "published $key"
  fi
done

# --- 2. Catalog, installers pages, invalidation -----------------------------------
if ((DRY_RUN)); then
  if [[ -n $(for c in "$PRODUCTS"/*.json; do versions_without_records "$work/listing.json" "$(jq -r .product "$c")"; done) ]]; then
    log "dry run: the catalog builds once those records exist"
  else
    build_catalog_json "$work/catalog.json"
    log "dry run: catalog builds: $(jq -c '[.products[] | {id, latest_version, versions: (.versions | length)}]' "$work/catalog.json")"
    if [[ $(jq '.products | length' "$work/catalog.json") == 0 ]]; then
      log "dry run: no published versions yet, the pages would not be rendered"
    else
      python3 "$KIT_DIR/render.py" "$work/catalog.json" "$work/kit-dry" >/dev/null || die "the page kit refuses this catalog"
      log "dry run: the page kit renders it ($(find "$work/kit-dry" -name index.html -not -path '*/_kit/*' | wc -l) pages)"
    fi
  fi
  exit 0
fi
publish_catalog
render_site "$work/catalog.json"
inv=$(aws cloudfront create-invalidation --region "$REGION" --distribution-id "$DISTRIBUTION_ID" \
  --paths '/*' --query Invalidation.Id --output text) || die "invalidation failed"
aws cloudfront wait invalidation-completed --region "$REGION" --distribution-id "$DISTRIBUTION_ID" \
  --id "$inv" || die "invalidation $inv didn't complete"
[[ $(curl -sS -A "$RBA_UA" "$BASE_URL/$CATALOG_KEY" | sha256sum | cut -d' ' -f1) == $(sha256sum <"$work/catalog.json" | cut -d' ' -f1) ]] \
  || die "the catalog served by $BASE_URL differs from the one written"
log "done: catalog and installers pages re-rendered and verified through $BASE_URL"
