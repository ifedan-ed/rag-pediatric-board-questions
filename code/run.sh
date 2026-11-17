#!/bin/sh
# Runs runner.js inside the study application image. Paths are placeholders: point them at your
# own environment file (gateway key), question bank and output folder.
set -e
docker run --rm --network host \
  --env-file ./study.env -e LIMIT -e PER_MODEL_CONCURRENCY \
  -v "$PWD/code/runner.js:/runner.js:ro" \
  -v "$PWD/private-data:/data:ro" \
  -v "$PWD/private-data/out:/out" \
  --entrypoint node study-app:latest /runner.js "$@"
