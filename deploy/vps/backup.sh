#!/usr/bin/env bash
# Backup: PostgreSQL dump + attachment files → ./backups/<timestamp>/
set -euo pipefail
cd "$(dirname "$0")/../.."
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="backups/$STAMP"
mkdir -p "$OUT"
docker compose exec -T db pg_dump -U postgres -d invoice_keeper --format=custom > "$OUT/db.dump"
docker compose exec -T api tar -C /data -czf - attachments > "$OUT/attachments.tar.gz"
ls -lh "$OUT"
echo "Restore: docker compose exec -T db pg_restore -U postgres -d invoice_keeper --clean --if-exists < $OUT/db.dump"
echo "         docker compose exec -T api tar -C /data -xzf - < $OUT/attachments.tar.gz"
