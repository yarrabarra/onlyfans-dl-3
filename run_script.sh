#!/bin/bash

MAIN_ARG="$1"

set -euo pipefail

poetry run python src/main.py $@
EXIT=$?

if [[ "$MAIN_ARG" == "--help" ]]; then
  exit 1
fi

if [[ "$EXIT" != "0" ]]; then
  echo "Main script failed, aborting."
  exit $EXIT
fi

poetry run python src/parse_tags.py
poetry run python src/sync_db_to_stash.py
