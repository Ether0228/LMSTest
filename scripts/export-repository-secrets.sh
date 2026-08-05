#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 OWNER/REPO" >&2
  exit 2
fi

repo="$1"
env_file="pipeline/.env"

if [[ ! -f "$env_file" ]]; then
  echo "Missing $env_file" >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI (gh) is required." >&2
  exit 1
fi

keys=(
  FEISHU_APP_ID
  FEISHU_APP_SECRET
  FEISHU_APP_TOKEN
  FEISHU_TABLE_ID
  FEISHU_ROSTER_TABLE_ID
  FEISHU_LIB_TABLE_ID
  FEISHU_MISSING_TABLE_ID
  FEISHU_GRADEBOOK_TABLE_ID
  FEISHU_CONFIG_TABLE_ID
  SCHOOLOGY_COOKIES
  SCHOOLOGY_SECTION_NIDS
  CURRENT_SEMESTER
  ACTIVE_SEMESTERS
  FEISHU_SUMMARY_TABLE_ID
  DATABASE_URL
  CACHE_TENANT_KEY
  FEISHU_WEBHOOK_URL
  SCHOOLOGY_GRADING_PERIOD
)

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

for key in "${keys[@]}"; do
  value="${!key-}"
  if [[ -z "$value" ]]; then
    echo "skip missing: $key"
    continue
  fi
  printf '%s' "$value" | gh secret set "$key" --repo "$repo"
  echo "set: $key"
done

echo "Done. Synced available secrets to $repo"
