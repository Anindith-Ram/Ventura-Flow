#!/usr/bin/env bash
# Start the investor_signal MCP server (stdio transport for OpenCode).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
exec uv run --project "$PROJECT_DIR" python -m investor_signal_mcp.server
