# shellcheck shell=bash
# Deployment settings (sourced by publish-release.sh and render-index.sh,
# after they define die).
#
# Public values (BASE_URL, REGION) come from config.env. The deployment's own
# values never live in this repository; they come from the file named by
# RBA_SETTINGS, NAME=value lines:
#   BUCKET, DISTRIBUTION_ID   the bucket and the CloudFront distribution
#   AWS_PROFILE_NAME, PUBLISH_ROLE_ARN
#                             local runs: the profile that assumes the role
#   CI_ROLE_NAME              --ci: the role the job must be running as
# In GitHub Actions the action writes that file from an SSM parameter after
# assuming the role, masking every value first (scripts/ci-settings.sh).
# shellcheck disable=SC2034  # used by the scripts that source this file

# shellcheck source-path=SCRIPTDIR/../.. source=config.env
source "$ROOT/config.env"
BUCKET="" DISTRIBUTION_ID="" AWS_PROFILE_NAME="" PUBLISH_ROLE_ARN="" CI_ROLE_NAME=""
if [[ -n ${RBA_SETTINGS:-} ]]; then
  [[ -f $RBA_SETTINGS ]] || die "RBA_SETTINGS names no file"
  # shellcheck source=/dev/null
  source "$RBA_SETTINGS"
fi

# need_settings <name>...: stop unless each setting is there.
need_settings() {
  local n
  for n; do
    [[ -n ${!n:-} ]] || die "$n is not set: point RBA_SETTINGS at the deployment's settings file"
  done
}
