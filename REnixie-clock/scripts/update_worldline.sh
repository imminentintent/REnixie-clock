#!/usr/bin/env bash
# Runs the estimator and commits its output to the `worldline-data` branch, so the
# 48 daily data commits never clutter the history of the main branch.
set -euo pipefail

BRANCH="worldline-data"
DIR="data-branch"

git config user.name "worldline-bot"
git config user.email "worldline-bot@users.noreply.github.com"

if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
  git fetch --depth=1 origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
  git worktree add -B "$BRANCH" "$DIR" "origin/$BRANCH"
  if [ ! -f "$DIR/.backfilled" ]; then   # one-off: recover the stories logged before stories.json existed
    git fetch --depth=500 origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" || true
    ${BACKFILL_CMD:-python worldline/worldline.py backfill --data "$DIR"} || true
    touch "$DIR/.backfilled"
  fi
else
  echo "first run: creating the $BRANCH branch"
  git worktree add --detach "$DIR"
  git -C "$DIR" checkout --orphan "$BRANCH"
  git -C "$DIR" rm -rf --quiet .
fi

# RUN_CMD exists so this script can be tested without network access.
${RUN_CMD:-python worldline/worldline.py run --data "$DIR"}

git -C "$DIR" add -A
if git -C "$DIR" diff --cached --quiet; then
  echo "nothing to commit"
  exit 0
fi
git -C "$DIR" commit -q -m "worldline update $(date -u +%Y-%m-%dT%H:%MZ)"
git -C "$DIR" push origin "HEAD:$BRANCH"
