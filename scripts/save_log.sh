#!/usr/bin/env bash
# Commit the locked sent log and push it. If another run pushed first (locked files can't be merged), start again
# from the latest data, add this run's log entry once more, and retry.
# Usage: scripts/save_log.sh "<commit message>" <kind> <date> [--request S3]
set -u
MSG="$1"; shift
git config user.name "vessel-logger"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
BR=$(git rev-parse --abbrev-ref HEAD)
for i in 1 2 3 4 5; do
  python scripts/vault.py seal
  git add -A vault
  git diff --cached --quiet || git commit -q -m "$MSG"
  if git pull --rebase --quiet && git push --quiet; then exit 0; fi
  echo "Sent log: another run saved first; retrying ($i)."
  git rebase --abort 2>/dev/null || true
  git fetch -q origin "$BR" && git reset -q --hard "origin/$BR"
  python scripts/vault.py open >/dev/null
  python scripts/sent_log.py "$@"
  sleep $((RANDOM % 10 + 5))
done
echo "::warning::The sent log could not be saved after several tries."
exit 0
