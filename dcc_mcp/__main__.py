import atexit
import logging
import sys
from pathlib import Path

from .app import build_core
from .server import build_server


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)  # stdout is the MCP channel
    config = sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "dcc_mcp.toml"
    core = build_core(config)
    atexit.register(core.runner.sessions.stop_all)
    build_server(core).run()


if __name__ == "__main__":
    main()
