"""Entry point for ``python -m src``."""

from __future__ import annotations

import logging

from src.config import AppConfig
from src.server import mcp


def main() -> None:
    config = AppConfig()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    mcp.run()


if __name__ == "__main__":
    main()
