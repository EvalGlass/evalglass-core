#!/usr/bin/env bash
#
# bump-version.sh — keep every version-bearing surface in lockstep (ADR 0022/0023).
#
# One repo means one version line. `.version-bump.json` declares the surfaces and formats;
# this script reads/writes them. The git tag is asserted at release time.
# It NEVER touches a host-owned / vendored runtime tree (evals/).
#
# Usage:
#   bump-version.sh --check [--expect X.Y.Z]   Report versions; exit non-zero on any drift
#   bump-version.sh --audit                    Report all surfaces + the expected git tag
#   bump-version.sh --set X.Y.Z                Rewrite every declared surface to X.Y.Z
#   bump-version.sh X.Y.Z                      Alias for --set X.Y.Z
#
# Options:
#   --root DIR    Operate on version files under DIR instead of the repo root (testing).
#   -h, --help    Show this help.
#
# Requires: bash, jq (config only), grep, sed.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG="$REPO_ROOT/.version-bump.json"
ROOT="$REPO_ROOT"

MODE=""
EXPECT=""
NEWVER=""

die() { echo "ERROR: $*" >&2; exit 1; }

usage() {
  sed -n '/^# Usage:/,/^# Requires:/s/^# \{0,1\}//p' "$0"
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)   MODE="check"; shift ;;
    --audit)   MODE="audit"; shift ;;
    --set)     MODE="set"; NEWVER="${2:-}"; shift 2 ;;
    --expect)  EXPECT="${2:-}"; shift 2 ;;
    --root)    ROOT="$(cd "${2:?--root needs a dir}" && pwd)"; shift 2 ;;
    -h|--help) usage 0 ;;
    --*)       die "unknown flag '$1' (see --help)" ;;
    *)         MODE="set"; NEWVER="$1"; shift ;;
  esac
done

[[ -n "$MODE" ]] || usage 1
[[ -f "$CONFIG" ]] || die ".version-bump.json not found at $CONFIG"
command -v jq >/dev/null || die "jq not found in PATH"

# Read one version value from a file, given its declared format + field. Never fails the script.
read_version() {
  local file="$1" fmt="$2" field="$3"
  [[ -f "$file" ]] || { echo "__MISSING__"; return 0; }
  case "$fmt" in
    json)   grep -E "\"$field\"[[:space:]]*:" "$file" | head -1 \
              | sed -E "s/.*\"$field\"[[:space:]]*:[[:space:]]*\"([^\"]*)\".*/\1/" || true ;;
    toml)   grep -E "^$field[[:space:]]*=" "$file" | head -1 \
              | sed -E "s/^$field[[:space:]]*=[[:space:]]*\"([^\"]*)\".*/\1/" || true ;;
    yaml)   grep -E "^$field:" "$file" | head -1 \
              | sed -E "s/^$field:[[:space:]]*\"?([^\"#[:space:]]+)\"?.*/\1/" || true ;;
    python) grep -E "^$field[[:space:]]*=" "$file" | head -1 \
              | sed -E "s/^$field[[:space:]]*=[[:space:]]*\"([^\"]*)\".*/\1/" || true ;;
    *)      die "unknown format '$fmt' in $CONFIG" ;;
  esac
}

# Rewrite the version value in-place, preserving the file's formatting.
write_version() {
  local file="$1" fmt="$2" field="$3" new="$4" tmp="$file.vbtmp"
  case "$fmt" in
    json|python)
      sed -E "s/(\"?$field\"?[[:space:]]*[:=][[:space:]]*\")[^\"]*(\")/\1$new\2/" "$file" >"$tmp" ;;
    toml)
      sed -E "s/^($field[[:space:]]*=[[:space:]]*\")[^\"]*(\")/\1$new\2/" "$file" >"$tmp" ;;
    yaml)
      sed -E "s/^($field:[[:space:]]*)\"?[^\"#[:space:]]+\"?/\1$new/" "$file" >"$tmp" ;;
    *)
      die "unknown format '$fmt'" ;;
  esac
  mv "$tmp" "$file"
}

# Stream "path<TAB>format<TAB>field" for each declared source.
sources() { jq -r '.version_sources[] | "\(.path)\t\(.format)\t\(.field)"' "$CONFIG"; }
tag_format() { jq -r '.tag_format' "$CONFIG"; }

collect() {
  # Echo "path<TAB>version" per source; refuse host-owned targets defensively.
  while IFS=$'\t' read -r path fmt field; do
    case "$path" in evals/*) die "refusing host-owned/vendored target: $path" ;; esac
    printf '%s\t%s\n' "$path" "$(read_version "$ROOT/$path" "$fmt" "$field")"
  done < <(sources)
}

cmd_check() {
  local drift=0 first="" v
  echo "Version surfaces (root: $ROOT):"
  while IFS=$'\t' read -r path ver; do
    printf '  %-40s %s\n' "$path" "$ver"
    [[ "$ver" == "__MISSING__" ]] && drift=1
    if [[ -z "$first" ]]; then first="$ver"; elif [[ "$ver" != "$first" ]]; then drift=1; fi
  done < <(collect)
  v="$first"
  if [[ $drift -ne 0 ]]; then
    echo "DRIFT: version-bearing surfaces are not in sync." >&2
    return 1
  fi
  echo "All surfaces in sync at $v"
  if [[ -n "$EXPECT" && "$EXPECT" != "$v" ]]; then
    echo "MISMATCH: expected $EXPECT but surfaces are at $v" >&2
    return 1
  fi
  return 0
}

cmd_audit() {
  cmd_check || true
  local common tag
  common="$(collect | cut -f2 | grep -v '__MISSING__' | sort | uniq -c | sort -rn | head -1 | awk '{print $2}')"
  tag="$(tag_format | sed "s/{version}/$common/")"
  echo ""
  echo "Expected git tag: $tag"
  return 0
}

cmd_set() {
  [[ "$NEWVER" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-].+)?$ ]] || die "'$NEWVER' is not a semver X.Y.Z"
  echo "Setting all declared surfaces to $NEWVER (root: $ROOT)"
  while IFS=$'\t' read -r path fmt field; do
    case "$path" in evals/*) die "refusing host-owned/vendored target: $path" ;; esac
    local file="$ROOT/$path"
    [[ -f "$file" ]] || { echo "  SKIP (missing): $path"; continue; }
    local old; old="$(read_version "$file" "$fmt" "$field")"
    write_version "$file" "$fmt" "$field" "$NEWVER"
    printf '  %-40s %s -> %s\n' "$path" "$old" "$NEWVER"
  done < <(sources)
  echo ""
  EXPECT="$NEWVER"
  cmd_check
}

case "$MODE" in
  check) cmd_check ;;
  audit) cmd_audit ;;
  set)   cmd_set ;;
  *)     usage 1 ;;
esac
