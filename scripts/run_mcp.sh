#!/bin/sh
# Cursor spawns MCP with a cwd outside this repo, so `python -m mattermost_mcp`
# fails with "No module named mattermost_mcp". Always run from the project root.
set -e
cd /Users/dsk/projects/letech/mattermost-mcp
export PYTHONUNBUFFERED=1
export PYTHONPATH="/Users/dsk/projects/letech/mattermost-mcp${PYTHONPATH:+:$PYTHONPATH}"
exec /Users/dsk/projects/letech/mattermost-mcp/.venv/bin/python -u -m mattermost_mcp
