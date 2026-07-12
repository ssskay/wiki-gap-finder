#!/usr/bin/env bash
# Build vet-sources.skill — a distributable zip of the Claude source-vetter skill.
#
# Layout inside the zip (top-level folder = the skill name so it drops straight
# into ~/.claude/skills/ or Claude's "add skill" prompt):
#
#   vet-sources/
#     SKILL.md
#     gapfinder/schemas/worklist.schema.json   # referenced by SKILL.md
#     gapfinder/schemas/verdicts.schema.json   # referenced by SKILL.md
#
# Only SKILL.md and the two JSON schemas it names ship. Everything the skill
# doesn't reference — tests/, output/, dist/, __pycache__, .git — is excluded.
# The schemas keep their repo-relative path so the "gapfinder/schemas/..."
# references inside SKILL.md still resolve from the skill root.
#
# Usage: scripts/build_skill.sh [OUTPUT]      (default: dist/vet-sources.skill)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

OUT="${1:-dist/vet-sources.skill}"
case "$OUT" in
  /*) ;;                      # already absolute
  *) OUT="$REPO_ROOT/$OUT" ;;
esac

SKILL_SRC="skills/vet-sources/SKILL.md"

# Files SKILL.md references (schema: gapfinder/schemas/*.json).
REFERENCED=(
  "gapfinder/schemas/worklist.schema.json"
  "gapfinder/schemas/verdicts.schema.json"
)

# Stage into a temp tree so the zip has a clean, single top-level vet-sources/.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/vet-sources"
cp "$SKILL_SRC" "$STAGE/vet-sources/SKILL.md"
for f in "${REFERENCED[@]}"; do
  mkdir -p "$STAGE/vet-sources/$(dirname "$f")"
  cp "$f" "$STAGE/vet-sources/$f"
done

mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"
( cd "$STAGE" && zip -r -X "$OUT" vet-sources >/dev/null )

echo "Built $OUT"
unzip -l "$OUT"
