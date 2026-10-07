#!/usr/bin/env bash
# Generic scan for anything identifying or secret in this public repository:
# every file (tracked and untracked, text only) and every commit's metadata.
# Fails on: a 12-digit number (an AWS account ID), an ARN with an account in
# it, AWS access key IDs, private keys, GitHub tokens, home-directory paths,
# and e-mail addresses other than no-reply ones. Real deployment values are
# never listed here (that would publish them); the maintainers scan for those
# separately, from their private checkout.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

patterns=(
  '(^|[^0-9A-Za-z])[0-9]{12}([^0-9A-Za-z]|$)'
  'arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:[0-9]'
  '(AKIA|ASIA)[0-9A-Z]{16}'
  'BEGIN [A-Z ]*PRIVATE KEY'
  '(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})'
  '(/home/[a-z]|/Users/[A-Za-z])'
)
# E-mail addresses allowed: GitHub no-reply, the co-author trailer, and test
# addresses under the reserved .invalid domain.
allowed_mail='@users\.noreply\.github\.com|^noreply@anthropic\.com$|@invalid$|\.invalid$'

fail=0
files=$(git ls-files --cached --others --exclude-standard)
for p in "${patterns[@]}"; do
  if hits=$(xargs -d '\n' grep -nIE -- "$p" <<<"$files" 2>/dev/null); then
    echo "scan: forbidden pattern /$p/:"; echo "$hits"; fail=1
  fi
done
mails=$(xargs -d '\n' grep -ohIE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' <<<"$files" 2>/dev/null | sort -u \
  | grep -vE "$allowed_mail" || true)
[[ -z $mails ]] || { echo "scan: e-mail addresses in files:"; echo "$mails"; fail=1; }

# Commit metadata: authors and committers use the no-reply address; messages
# get the same pattern scan.
if git rev-parse -q --verify HEAD >/dev/null; then
  bad=$(git log --all --format='%ae%n%ce' | sort -u | grep -vE "$allowed_mail" || true)
  [[ -z $bad ]] || { echo "scan: commit identities that aren't no-reply:"; echo "$bad"; fail=1; }
  msgs=$(git log --all --format='%B')
  for p in "${patterns[@]}"; do
    if grep -nE -- "$p" <<<"$msgs"; then echo "scan: forbidden pattern /$p/ in a commit message"; fail=1; fi
  done
  mails=$(grep -ohE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' <<<"$msgs" | sort -u | grep -vE "$allowed_mail" || true)
  [[ -z $mails ]] || { echo "scan: e-mail addresses in commit messages:"; echo "$mails"; fail=1; }
fi
((fail == 0)) && echo "scan: clean ($(wc -l <<<"$files") files)"
exit "$fail"
