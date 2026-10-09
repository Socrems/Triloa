"""Run Triloa's desktop app or local translation service."""

from __future__ import annotations

import sys

from .paths import configure_paths
from .diagnostics import trace


def main() -> int:
    configure_paths()
    trace("configured paths")
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        from .selftest import run

        return run()
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        from .server import make_server

        server = make_server()
        print("Triloa local API: http://127.0.0.1:8765", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.server_close()
        return 0

    trace("importing desktop")
    from .desktop import run_desktop
    trace("imported desktop")

    return run_desktop()


if __name__ == "__main__":
    raise SystemExit(main())
