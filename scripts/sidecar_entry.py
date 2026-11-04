"""PyInstaller entrypoint for the openFuyao sidecar binary."""

from witty_service.sidecar.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
