# shellcheck shell=bash
# Per-run scratch directories (sourced by publish-release.sh, render-index.sh
# and the tests). Each run makes its own with mktemp and removes it on exit,
# so nothing piles up.
#
# scratch_cleanup <dir>: remove a run's own scratch directory, recursively,
# only after resolving it and checking it is /tmp/rba-<name> (one level, no
# dots), not a symlink, and owned by the current user. Anything else is left
# alone, with a note (for example when TMPDIR points outside /tmp). Prints
# the real path it removes. SCRATCH_CLEANUP_DRY=1 runs every check, then
# only says what it would remove (the tests use it for paths it must refuse).

scratch_cleanup() {
  local dir=${1:-} real
  [[ -n $dir && -e $dir ]] || return 0
  if [[ -L $dir ]]; then echo "scratch: not removing $dir (a symlink)" >&2; return 0; fi
  real=$(realpath -e -- "$dir") || return 0
  if [[ ! $real =~ ^/tmp/rba-[A-Za-z0-9_-]+$ ]]; then
    echo "scratch: not removing $real (not /tmp/rba-<name>)" >&2; return 0
  fi
  if [[ $(stat -c %u -- "$real") != "$(id -u)" ]]; then
    echo "scratch: not removing $real (not owned by $(id -un))" >&2; return 0
  fi
  if [[ ${SCRATCH_CLEANUP_DRY:-} == 1 ]]; then echo "scratch: would remove $real" >&2; return 0; fi
  echo "scratch: removing $real" >&2
  rm -rf --one-file-system -- "$real"
}
