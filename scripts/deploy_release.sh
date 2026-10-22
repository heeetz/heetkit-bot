#!/usr/bin/env bash
# Run only on the existing Linux host, after an explicit deployment request.
set -euo pipefail
exec python3 "$(dirname -- "${BASH_SOURCE[0]}")/deploy_release.py" "$@"
