#!/bin/bash
# Launch github-mcp-server with PAT from secure file.
# Token file: ~/.config/github-mcp-token (not in repo, user-only permissions)
TOKEN_FILE="$HOME/.config/github-mcp-token"
if [ -f "$TOKEN_FILE" ]; then
    export GITHUB_PERSONAL_ACCESS_TOKEN=$(cat "$TOKEN_FILE")
else
    echo "Error: $TOKEN_FILE not found. Create it with your GitHub PAT." >&2
    exit 1
fi
exec npx -y @modelcontextprotocol/server-github "$@"
