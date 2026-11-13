"""Command-line entry point that starts the local web app."""

from __future__ import annotations

import sys

from leadgen.config import ConfigError, Settings


def main(argv: list[str] | None = None) -> int:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    import uvicorn

    from leadgen.web.app import create_app

    print(f"Open http://{settings.host}:{settings.port}/ in your browser")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")
    return 0
