"""Entry point for MCP clients that cannot set a working directory (Claude Desktop)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dcc_mcp.__main__ import main  # noqa: E402

main()
