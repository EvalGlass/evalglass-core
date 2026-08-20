#!/usr/bin/env bash
#
# sync-to-codex-plugin.sh — sync the canonical EvalGlass plugin content into the Codex
# marketplace fork, deterministically and without forking skill content (plan §8.4; ADR 0023).
#
# One canonical source, thin per-runtime manifests. The Codex payload is the shared skills/ tree,
# the committed .codex-plugin/ manifest, the AGENTS.md bootstrap, plugin-docs/, and assets/.
# Runtime-specific infra (src/, .claude-plugin/, hooks/, commands/, scripts/, tests/, docs/, dev
# gates, CLAUDE.md) is never synced — a Codex plugin ships skills only.
#
# Usage:
#   sync-to-codex-plugin.sh --stage DIR        Assemble the Codex payload into DIR (network-free)
#   sync-to-codex-plugin.sh --dry-run          Stage to a temp dir and print the plan (default)
#   sync-to-codex-plugin.sh --fork ORG/REPO    Live sync: clone the fork, overlay, open a PR
#   sync-to-codex-plugin.sh --fork ... --bootstrap   Create the plugin dir in the fork if absent
#   sync-to-codex-plugin.sh --fork ... --yes         Skip the confirmation prompt
#
# Options:
#   --dest-rel PATH   Plugin path inside the fork (default: plugins/evalglass).
#   -h, --help        Show this help.
#
# Determinism: the same source produces a byte-identical stage every run, so two back-to-back
# runs verify the tool itself. The live --fork path needs `gh` authenticated and the destination
# fork to exist; it is a maintainer step (the open Codex-fork question, ADR 0023).
#
# Requires: bash, rsync; plus git + gh for the live --fork path.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$(cd "$SCRIPT_DIR/.." && pwd)"

# The canonical Codex plugin payload — explicit allowlist (inherently deterministic).
INCLUDE_DIRS=("skills" ".codex-plugin" "plugin-docs" "assets")
INCLUDE_FILES=("AGENTS.md")

MODE="dry-run"
STAGE_DIR=""
FORK="${EVALGLASS_CODEX_FORK:-}"
DEST_REL="plugins/evalglass"
BOOTSTRAP=0
YES=0

die() { echo "ERROR: $*" >&2; exit 1; }

usage() {
  sed -n '/^# Usage:/,/^# Requires:/s/^# \{0,1\}//p' "$0"
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stage)     MODE="stage"; STAGE_DIR="${2:?--stage needs a dir}"; shift 2 ;;
    -n|--dry-run) MODE="dry-run"; shift ;;
    --fork)      MODE="live"; FORK="${2:?--fork needs ORG/REPO}"; shift 2 ;;
    --dest-rel)  DEST_REL="${2:?--dest-rel needs a path}"; shift 2 ;;
    --bootstrap) BOOTSTRAP=1; shift ;;
    -y|--yes)    YES=1; shift ;;
    -h|--help)   usage 0 ;;
    *)           die "unknown arg '$1' (see --help)" ;;
  esac
done

command -v rsync >/dev/null || die "rsync not found in PATH"

# Assemble the deterministic payload into $1 (cleaned first).
stage_into() {
  local dest="$1"
  mkdir -p "$dest"
  # Clean only our managed subpaths so re-staging is idempotent and deterministic.
  local p
  for p in "${INCLUDE_DIRS[@]}" "${INCLUDE_FILES[@]}"; do
    rm -rf "${dest:?}/$p"
  done
  for p in "${INCLUDE_DIRS[@]}"; do
    [[ -d "$SRC/$p" ]] || continue
    mkdir -p "$dest/$p"
    rsync -a --delete --exclude='.DS_Store' "$SRC/$p/" "$dest/$p/"
  done
  for p in "${INCLUDE_FILES[@]}"; do
    [[ -f "$SRC/$p" ]] || continue
    rsync -a "$SRC/$p" "$dest/$p"
  done
}

print_plan() {
  local dest="$1"
  echo "Codex payload staged at: $dest"
  echo "Included:"
  local p
  for p in "${INCLUDE_DIRS[@]}" "${INCLUDE_FILES[@]}"; do
    [[ -e "$dest/$p" ]] && echo "  + $p"
  done
  echo "Excluded (runtime-specific / not a Codex plugin surface):"
  echo "  - src/ .claude-plugin/ hooks/ commands/ scripts/ tests/ docs/ .github/ .claude/ CLAUDE.md"
}

case "$MODE" in
  stage)
    stage_into "$STAGE_DIR"
    print_plan "$STAGE_DIR"
    ;;

  dry-run)
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    stage_into "$tmp/payload"
    print_plan "$tmp/payload"
    echo ""
    echo "(dry-run: nothing written outside the temp stage; pass --fork ORG/REPO to sync for real)"
    ;;

  live)
    [[ -n "$FORK" ]] || die "live sync needs --fork ORG/REPO (or \$EVALGLASS_CODEX_FORK)"
    command -v git >/dev/null || die "git not found in PATH"
    command -v gh >/dev/null  || die "gh not found — install GitHub CLI for the live path"
    gh auth status >/dev/null 2>&1 || die "gh not authenticated — run 'gh auth login'"

    src_sha="$(cd "$SRC" && git rev-parse --short HEAD)"
    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT
    echo "Cloning $FORK ..."
    gh repo clone "$FORK" "$work/fork" -- --depth 1 >/dev/null || die "clone failed for $FORK"
    dest="$work/fork/$DEST_REL"
    if [[ ! -d "$dest" ]]; then
      [[ $BOOTSTRAP -eq 1 ]] || die "$DEST_REL absent in fork (pass --bootstrap to create it)"
      mkdir -p "$dest"
    fi
    stage_into "$dest"
    print_plan "$dest"
    ( cd "$work/fork" && git add -A && git status --porcelain ) | sed 's/^/  /'
    if [[ $YES -ne 1 ]]; then
      read -rp "Open a sync PR to $FORK from evalglass@$src_sha? [y/N] " ans
      [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "aborted"; exit 1; }
    fi
    branch="sync-evalglass-$src_sha"
    ( cd "$work/fork" \
        && git checkout -b "$branch" \
        && git commit -m "sync: EvalGlass plugin @ $src_sha" \
        && git push -u origin "$branch" \
        && gh pr create --fill --base main --head "$branch" )
    ;;

  *)
    usage 1 ;;
esac
