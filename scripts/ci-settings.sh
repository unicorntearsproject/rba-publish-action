#!/usr/bin/env bash
# The action's settings steps. The caller's logs may be public, so every
# deployment value is masked (::add-mask::) before anything can print it.
#
#   ci-settings.sh mask         mask ROLE_ARN and its account ID (before the
#                               OIDC step; nothing to do without ROLE_ARN)
#   ci-settings.sh read <file>  with the role's credentials: read the SSM
#                               parameter SETTINGS_PARAMETER (JSON
#                               {"bucket": ..., "distribution_id": ...}),
#                               mask both values, and write the RBA_SETTINGS
#                               file publish-release.sh reads
#
# Never prints a value it hasn't masked first. Values are checked against
# their AWS formats before they're written, so the file is safe to source.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source-path=SCRIPTDIR/.. source=config.env
source "$ROOT/config.env"
die() { echo "::error::settings: $*" >&2; exit 1; }

ROLE_RE='^arn:aws:iam::([0-9]{12}):role/([A-Za-z0-9+=,.@_/-]+)$'

mask_role() {
  [[ -n ${ROLE_ARN:-} ]] || return 0
  # On a mismatch, say so without echoing the input.
  [[ $ROLE_ARN =~ $ROLE_RE ]] || die "role-arn isn't an IAM role ARN (arn:aws:iam::<account>:role/<name>)"
  echo "::add-mask::${BASH_REMATCH[1]}"
  echo "::add-mask::$ROLE_ARN"
}

read_settings() {
  local out=$1 value bucket dist role
  [[ -n ${ROLE_ARN:-} ]] || die "role-arn is needed to publish"
  [[ $ROLE_ARN =~ $ROLE_RE ]] || die "role-arn isn't an IAM role ARN"
  role=${BASH_REMATCH[2]##*/}
  [[ -n ${SETTINGS_PARAMETER:-} ]] || die "settings-parameter is empty"
  # An AWS error here names ARNs with the account ID, which mask_role masked.
  value=$(aws ssm get-parameter --region "$REGION" --name "$SETTINGS_PARAMETER" \
    --query Parameter.Value --output text) || die "can't read the settings parameter"
  bucket=$(jq -er '.bucket | strings' <<<"$value" 2>/dev/null) || die "the settings parameter has no bucket"
  dist=$(jq -er '.distribution_id | strings' <<<"$value" 2>/dev/null) || die "the settings parameter has no distribution_id"
  [[ $bucket =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] || die "the settings parameter's bucket isn't a bucket name"
  [[ $dist =~ ^E[A-Z0-9]{5,20}$ ]] || die "the settings parameter's distribution_id isn't a distribution ID"
  echo "::add-mask::$bucket"
  echo "::add-mask::$dist"
  printf 'BUCKET=%q\nDISTRIBUTION_ID=%q\nCI_ROLE_NAME=%q\n' "$bucket" "$dist" "$role" >"$out"
  echo "settings: read from the parameter (bucket and distribution masked)"
}

case ${1:-} in
  mask) mask_role ;;
  read) [[ -n ${2:-} ]] || die "read needs an output file"; read_settings "$2" ;;
  *) die "usage: ci-settings.sh mask | read <file>" ;;
esac
