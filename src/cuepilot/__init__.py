import sys


def main() -> None:
    if sys.platform == "darwin":
        from cuepilot.macos import run

        run()
        return

    raise SystemExit(f"CuePilot does not have a {sys.platform} app yet.")


if __name__ == "__main__":
    main()
