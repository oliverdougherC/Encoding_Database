#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
This script is intentionally disabled.

Reason:
- The current backend does not expose /admin/api-keys endpoints.
- Keeping a "working" key-management script would imply production controls that do not exist.

Action:
- Use ingest mode + rate limits currently implemented by the backend.
- Re-enable this script only after admin key APIs are implemented server-side.
EOF

exit 1
