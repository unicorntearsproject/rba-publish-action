# shellcheck shell=bash
# GitHub calls for publish-release.sh (sourced; docs/publishing.md).
#
# Both use `gh`. Locally that is the user's own gh auth; in CI the caller
# passes tokens through PUBLISH_SOURCE_TOKEN (read the source repo's tags)
# and PUBLISH_DISPATCH_TOKEN (start the downstream workflow). When a token
# variable is unset, gh falls back to its own auth.

# gh_as <token> <gh args...>: run gh with that token, or its own auth if empty.
gh_as() {
  local token=$1
  shift
  if [[ -n $token ]]; then GH_TOKEN=$token gh "$@"; else gh "$@"; fi
}

# resolve_tag_commit <owner/repo> <tag>: print the commit the tag points to,
# dereferencing annotated tags. Fails closed: a missing tag, an API error or
# an unexpected object type is an error, never "skip".
resolve_tag_commit() {
  local repo=$1 tag=$2 out type sha depth=0
  out=$(gh_as "${PUBLISH_SOURCE_TOKEN:-}" api "repos/$repo/git/ref/tags/$tag" \
    --jq '.object.type + " " + .object.sha' 2>&1) || {
    if grep -q 'HTTP 404' <<<"$out"; then
      echo "tag $tag doesn't exist in $repo" >&2
    else
      echo "can't read tag $tag from $repo: $out" >&2
    fi
    return 1
  }
  read -r type sha <<<"$out"
  while [[ $type == tag ]]; do
    ((++depth <= 5)) || { echo "tag $tag: too many nested tag objects" >&2; return 1; }
    out=$(gh_as "${PUBLISH_SOURCE_TOKEN:-}" api "repos/$repo/git/tags/$sha" \
      --jq '.object.type + " " + .object.sha' 2>&1) || { echo "can't read tag object $sha: $out" >&2; return 1; }
    read -r type sha <<<"$out"
  done
  [[ $type == commit && $sha =~ ^[0-9a-f]{40}$ ]] || { echo "tag $tag points at $type ${sha:-?}, not a commit" >&2; return 1; }
  echo "$sha"
}

# notify_published <owner/repo> <workflow file> <ref> <version>: start the
# downstream deploy with a workflow_dispatch (inputs version and tag =
# v<version>; never dry_run). Needs only Actions: write on that repo. Never
# fails the caller: the release is already published. On failure it prints
# a loud warning and the exact command to retry by hand.
notify_published() {
  local repo=$1 workflow=$2 ref=$3 version=$4 out
  local call=(api -X POST "repos/$repo/actions/workflows/$workflow/dispatches"
    -f "ref=$ref" -f "inputs[version]=$version" -f "inputs[tag]=v$version")
  if out=$(gh_as "${PUBLISH_DISPATCH_TOKEN:-}" "${call[@]}" 2>&1); then
    echo "publish: started $workflow on $repo@$ref (version $version, tag v$version)"
    return 0
  fi
  cat >&2 <<EOF
publish: ======================================================================
publish: WARN the release IS published, but starting $workflow on $repo FAILED:
publish:   $out
publish: Start the deploy by hand:
publish:   gh api -X POST repos/$repo/actions/workflows/$workflow/dispatches -f ref=$ref -f 'inputs[version]=$version' -f 'inputs[tag]=v$version'
publish: ======================================================================
EOF
  return 0
}
