#!/usr/bin/env bash
set -euo pipefail

# Generate the Fly build context without making any Fly API calls. The publisher
# does not support -c, so add the configuration after generating the context.
database=${1:?Usage: package-datasette.sh DATABASE OUTPUT_DIRECTORY}
output=${2:?Usage: package-datasette.sh DATABASE OUTPUT_DIRECTORY}
datasette publish fly "$database" \
  --app simonwillisonblog-backup \
  --metadata metadata.yml \
  --plugins-dir plugins \
  --extra-options "--config datasette.yml" \
  --install "-r requirements-datasette.txt" \
  --generate-dir "$output"
cp datasette.yml requirements-datasette.txt "$output/"
