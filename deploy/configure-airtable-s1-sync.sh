#!/usr/bin/env bash
# Create the private runtime configuration without putting the Airtable token
# into shell history, a command line, or the Git repository.
set -euo pipefail

CONFIG_PATH=/etc/lmstest/airtable-s1-sync.env

if [[ ${EUID} -ne 0 ]]; then
  echo "请以 root 身份运行此脚本。" >&2
  exit 1
fi

if [[ -e "$CONFIG_PATH" ]]; then
  echo "配置文件已存在：$CONFIG_PATH；为避免覆盖，请先人工确认后再处理。" >&2
  exit 1
fi

read -r -s -p "请输入 Airtable Personal Access Token（输入不显示）: " airtable_token
echo
if [[ -z "$airtable_token" ]]; then
  echo "Airtable Token 不能为空。" >&2
  exit 1
fi

install -d -m 0700 /etc/lmstest
umask 077
{
  printf 'AIRTABLE_TOKEN=%s\n' "$airtable_token"
  printf '%s\n' 'AIRTABLE_BASE_ID=app0bWMb7eh9q5eoz'
  printf '%s\n' 'AIRTABLE_STUDENT_TABLE_ID=tblJXvnYQSHouSlIF'
  printf '%s\n' 'AIRTABLE_S1_TABLE_ID=tblNPDd714aDtHcOl'
  printf '%s\n' 'FEISHU_BASE_TOKEN=GSFqbOVH9awprdsGlMLcjhAhnje'
  printf '%s\n' 'FEISHU_SEMESTER_RECORD_ID=rec27ZqS4bUgIj'
  printf '%s\n' 'LARK_PROFILE=source-school'
  printf '%s\n' 'LARK_IDENTITY=user'
} >"$CONFIG_PATH"
unset airtable_token
chmod 0600 "$CONFIG_PATH"
echo "已创建私有配置文件：$CONFIG_PATH"
