#!/bin/bash
set -euo pipefail

REPO_URL="https://github.com/${GITHUB_REPOSITORY}"
RUNNER_NAME="${RUNNER_NAME:-self-hosted-wsl2}"
RUNNER_LABELS="${RUNNER_LABELS:-self-hosted,linux,x64}"

# Get a fresh registration token via GitHub API
if [ -z "${RUNNER_TOKEN:-}" ]; then
    echo "Requesting registration token..."
    RUNNER_TOKEN=$(curl -s -X POST \
        -H "Authorization: token ${GITHUB_PAT}" \
        -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/runners/registration-token" \
        | jq -r .token)
fi

# Configure the runner (ephemeral = de-registers after one job)
./config.sh \
    --url "${REPO_URL}" \
    --token "${RUNNER_TOKEN}" \
    --name "${RUNNER_NAME}" \
    --labels "${RUNNER_LABELS}" \
    --ephemeral \
    --unattended \
    --replace

# Cleanup on exit: remove runner registration
cleanup() {
    echo "Removing runner..."
    REMOVE_TOKEN=$(curl -s -X POST \
        -H "Authorization: token ${GITHUB_PAT}" \
        -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/runners/remove-token" \
        | jq -r .token)
    ./config.sh remove --token "${REMOVE_TOKEN}" 2>/dev/null || true
}
trap cleanup EXIT

# Run
./run.sh
