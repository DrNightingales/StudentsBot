#!/usr/bin/env bash
  set -euo pipefail

  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  docker run -it --rm \
    --name students-crm-dev \
    --env-file "$ROOT_DIR/.env" \
    -p 8000:8000 \
    -v "$ROOT_DIR":/app:Z \
    students-crm