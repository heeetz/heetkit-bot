"""Canonical desktop application entry point."""

from app.webview_host import main as webview_main


def main() -> None:
    webview_main()


if __name__ == "__main__":
    main()
