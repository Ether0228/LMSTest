#!/usr/bin/env bash
set -euo pipefail

source /etc/lmstest/airtable-s1-sync.env
cd /srv/lmstest
python3 pipeline/sync_airtable_s1_enrollment.py --apply
