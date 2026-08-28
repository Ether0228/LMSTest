#!/usr/bin/env bash
set -euo pipefail

# The env file intentionally contains plain KEY=value lines.  Export them only
# for this process so Python receives the Airtable token without making it
# globally persistent in the service account shell.
set -a
source /etc/lmstest/airtable-s1-sync.env
set +a
cd /srv/lmstest
python3 pipeline/sync_airtable_s1_enrollment.py --apply
