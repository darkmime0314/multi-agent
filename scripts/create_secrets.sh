#!/usr/bin/env bash
# Create Kubernetes secrets from an env file.
# Usage: ./scripts/create_secrets.sh [path_to_env]

set -euo pipefail

ENV_FILE="${1:-.env}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Env file '$ENV_FILE' not found" >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

kubectl create secret generic anthropic-api-key \
  --from-literal=ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic openai-api-key \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic langsmith-api-key \
  --from-literal=LANGSMITH_API_KEY="$LANGSMITH_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -
