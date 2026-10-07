# shellcheck shell=bash
# HTTP helpers for publish-release.sh. Plain curl features only, so they work
# with the curl on every runner we support: ubuntu-22.04's curl 7.81 has no
# -w '%header{…}' (7.84+) and prints such a format literally.

# head_status_length <url>: print "<status> <content-length>" for a HEAD
# request, read from the response headers ("-" when there's no length).
# Fails if curl fails or no status line comes back.
head_status_length() {
  local h
  h=$(curl -sS -I --connect-timeout 20 --max-time 60 "$1") || return 1
  awk '{ sub(/\r$/, "") }
       /^HTTP\// { code = $2; len = "" }
       tolower($1) == "content-length:" { len = $2 }
       END { if (code == "") exit 1; print code, (len == "" ? "-" : len) }' <<<"$h"
}
