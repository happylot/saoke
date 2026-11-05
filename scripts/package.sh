#!/usr/bin/env bash
set -euo pipefail

revision="${1:-$(git rev-parse HEAD)}"
if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then
  printf '%s\n' 'Expected a full Git commit SHA.' >&2
  exit 1
fi

node scripts/check.mjs
mkdir -p .deploy/site
cp index.html .deploy/site/index.html
mkdir -p .deploy/site/server
cp server/app.py .deploy/site/server/app.py
printf '%s\n' "$revision" > .deploy/site/version.txt
# Explicit file list: local statements and financial data never enter the archive.
COPYFILE_DISABLE=1 tar -czf .deploy/site.tar.gz -C .deploy/site index.html server/app.py version.txt
printf '%s\n' "Packaged revision $revision"
