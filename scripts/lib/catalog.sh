# shellcheck shell=bash
# catalog.json from the bucket (sourced by publish-release.sh and
# render-index.sh; docs/catalog.md).
#
# Expects from the caller: ROOT, BUCKET, REGION, BASE_URL, work (a scratch
# directory), the functions die/log, and AWS credentials for the publish
# role already in the environment.
# shellcheck disable=SC2154  # work, BUCKET, REGION, BASE_URL, ROOT: set by the caller

CATALOG_KEY=catalog/latest/catalog.json

# b64_to_hex: S3's base64 SHA-256 checksum as 64 hex characters.
b64_to_hex() { base64 -d | od -An -v -tx1 | tr -d ' \n'; }

# build_catalog_json <out>: list the bucket, fetch every release record and
# every latest/ alias's SHA-256, and build catalog.json into <out>. Stops on
# any inconsistency (catalog.py says what).
build_catalog_json() {
  local out=$1 conf product key alias version sha
  local listing records shas
  # A fresh directory per call: nothing is ever deleted.
  records=$(mktemp -d "$work/catalog-XXXX") || die "can't create a scratch directory"
  listing=$records/listing.json shas=$records/alias-sha.json
  aws s3api list-objects-v2 --bucket "$BUCKET" --region "$REGION" --query Contents --output json >"$listing" \
    || die "can't list the bucket"
  echo '{}' >"$shas"
  for conf in "${PRODUCTS:-$ROOT/scripts/products}"/*.json; do
    product=$(jq -r .product "$conf")
    mkdir -p "$records/records/$product"
    while read -r key; do
      [[ -n $key ]] || continue
      version=$(cut -d/ -f2 <<<"$key")
      aws s3api get-object --bucket "$BUCKET" --region "$REGION" --key "$key" "$records/records/$product/$version.json" \
        >/dev/null || die "can't read $key"
    done < <(jq -r --arg p "$product" '.[]? | .Key | select(startswith($p + "/") and endswith("/release.json"))' "$listing")
    while read -r alias; do
      key=$product/latest/$alias
      jq -e --arg k "$key" 'any(.[]?; .Key == $k)' "$listing" >/dev/null || continue
      sha=$(aws s3api head-object --bucket "$BUCKET" --region "$REGION" --key "$key" --checksum-mode ENABLED \
        --query ChecksumSHA256 --output text) || die "can't read $key"
      [[ $sha != None && -n $sha ]] || die "$key has no stored SHA-256 (uploaded without a checksum)"
      jq --arg k "$key" --arg s "$(b64_to_hex <<<"$sha")" '. + {($k): $s}' "$shas" >"$shas.new" && mv -- "$shas.new" "$shas"
    done < <(jq -r '.aliases[]' "$conf")
  done
  python3 "$ROOT/scripts/lib/catalog.py" build --confs "${PRODUCTS:-$ROOT/scripts/products}"/*.json --listing "$listing" \
    --alias-sha "$shas" --records "$records/records" --base-url "$BASE_URL" \
    --generated "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$out" || die "catalog build failed"
}

# versions_without_records <listing> <product> [<except>]: the version
# folders of <product> in a list-objects-v2 Contents file that have no
# release.json, space-separated (except <except>, the version being
# published, whose record comes later in the same run).
versions_without_records() {
  jq -r --arg p "$2/" --arg x "${3:-}" '[.[]? | .Key | select(startswith($p)) | split("/")] as $k
    | ($k | map(select(length >= 3 and .[1] != "latest" and .[1] != $x) | .[1]) | unique) as $versions
    | ($k | map(select(length == 3 and .[2] == "release.json") | .[1]) | unique) as $records
    | ($versions - $records) | join(" ")' "$1"
}

# publish_catalog: build catalog.json and replace catalog/latest/catalog.json.
publish_catalog() {
  local out=$work/catalog.json
  build_catalog_json "$out"
  aws s3api put-object --bucket "$BUCKET" --region "$REGION" --key "$CATALOG_KEY" --body "$out" \
    --checksum-sha256 "$(openssl dgst -sha256 -binary "$out" | base64)" \
    --content-type 'application/json' --cache-control 'public, max-age=60' >/dev/null \
    || die "can't write $CATALOG_KEY"
  log "catalog: $(jq -r '[.products[] | "\(.id) \(.latest_version) (\(.versions | length) versions)"] | join(", ")' "$out")"
}

# The page kit (RBA Web Site's, vendored at a pinned commit; vendor/README.md).
KIT_DIR=${KIT_DIR:-$ROOT/vendor/software-kit}

# kit_content_type <name>: Content-Type for a kit output file.
kit_content_type() {
  case $1 in
    *.html) echo 'text/html; charset=utf-8' ;;
    *.css) echo 'text/css; charset=utf-8' ;;
    *.woff2) echo 'font/woff2' ;;
    *.webp) echo 'image/webp' ;;
    *.txt) echo 'text/plain; charset=utf-8' ;;
    *) die "kit: no content type for $1" ;;
  esac
}

# render_site <catalog.json>: render the installers pages with the page kit
# and upload them. Fingerprinted kit assets first, as new keys only
# (If-None-Match; identical is fine, different aborts), then the kit's
# pages (replaced, short cache), then our version and latest/ folder
# pages, which link the kit's stylesheet (the CSP allows no inline style).
render_site() {
  local catalog=$1 out f key css have want
  out=$(mktemp -d "$work/site-XXXX") || die "can't create a scratch directory"
  if [[ $KIT_DIR == "$ROOT/vendor/software-kit" ]]; then
    # The vendored kit must be byte for byte the pinned one (Web Site's manifest).
    (cd "$ROOT/vendor" && sha256sum -c --quiet software-kit.sha256) >/dev/null 2>&1 \
      || die "vendor/software-kit doesn't match vendor/software-kit.sha256"
  fi
  if [[ $(jq '.products | length' "$catalog") == 0 ]]; then
    # Nothing published yet: the kit renders nothing for an empty catalog,
    # and there are no old pages to replace. The pages appear with the
    # first publish.
    log "pages: no published versions yet, nothing to render"
    return 0
  fi
  python3 "$KIT_DIR/render.py" "$catalog" "$out/kit" || die "the page kit refused the catalog"
  [[ -f $out/kit/index.html ]] || die "the page kit wrote no index.html"
  while IFS= read -r f; do
    key=${f#"$out/kit/"}
    [[ $key =~ ^_kit/[A-Za-z0-9._-]+\.[0-9a-f]{10}\.[a-z0-9]+$ ]] || die "kit asset $key isn't fingerprinted"
    want=$(openssl dgst -sha256 -binary "$f" | base64)
    if ! aws s3api put-object --bucket "$BUCKET" --region "$REGION" --key "$key" --body "$f" --if-none-match '*' \
        --checksum-sha256 "$want" --content-type "$(kit_content_type "$key")" \
        --cache-control 'public, max-age=31536000, immutable' >/dev/null 2>"$out/err"; then
      grep -q PreconditionFailed "$out/err" || die "can't create $key: $(cat "$out/err")"
      have=$(aws s3api head-object --bucket "$BUCKET" --region "$REGION" --key "$key" --checksum-mode ENABLED \
        --query ChecksumSHA256 --output text) || die "can't read back $key"
      [[ $have == "$want" ]] || die "$key already exists with different content"
    fi
  done < <(find "$out/kit/_kit" -type f | sort)
  css=$(cd "$out/kit" && find _kit -maxdepth 1 -name 'kit.*.css' | sort)
  [[ $(wc -l <<<"$css") == 1 && -n $css ]] || die "expected exactly one _kit/kit.*.css, found: ${css:-none}"
  while IFS= read -r f; do
    key=${f#"$out/kit/"}
    aws s3api put-object --bucket "$BUCKET" --region "$REGION" --key "$key" --body "$f" \
      --checksum-sha256 "$(openssl dgst -sha256 -binary "$f" | base64)" \
      --content-type 'text/html; charset=utf-8' --cache-control 'public, max-age=300' >/dev/null \
      || die "can't write $key"
  done < <(find "$out/kit" -name index.html -not -path "$out/kit/_kit/*" | sort)
  aws s3api list-objects-v2 --bucket "$BUCKET" --region "$REGION" --query Contents --output json >"$out/listing.json" \
    || die "can't list the bucket"
  while IFS= read -r key; do
    aws s3api put-object --bucket "$BUCKET" --region "$REGION" --key "$key" --body "$out/folders/$key" \
      --content-type 'text/html; charset=utf-8' --cache-control 'public, max-age=300' >/dev/null \
      || die "can't write $key"
  done < <(python3 "$ROOT/scripts/lib/release_check.py" indexes --listing "$out/listing.json" \
    --confs "${PRODUCTS:-$ROOT/scripts/products}"/*.json --out "$out/folders" --stylesheet "/$css" --folders-only)
  log "pages: kit $(find "$out/kit" -name index.html -not -path '*/_kit/*' | wc -l), folders $(find "$out/folders" -name index.html | wc -l), kit assets $(find "$out/kit/_kit" -type f | wc -l)"
}
