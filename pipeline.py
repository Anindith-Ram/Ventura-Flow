"""Top-level launcher for the Research Intelligence Pipeline.

Default behaviour: start the FastAPI server, open the browser to the GUI, and
let the VC review / adjust their profile before kicking off a run.

Headless / CLI fallbacks:
    python pipeline.py --cli single        # run one round with saved profile
    python pipeline.py --cli autonomous    # run autonomous mode
    python pipeline.py --no-browser        # start server without opening browser
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import threading
import time
import webbrowser

from shared.config import settings


def _open_browser(url: str, delay: float = 1.2) -> None:
    def _go() -> None:
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_go, daemon=True).start()


def serve(open_browser: bool = True) -> None:
    url = f"http://{settings.gui_host}:{settings.gui_port}"
    print(f"→ GUI starting at {url}")
    if open_browser:
        _open_browser(url)
    from gui.server import run_server
    run_server()


async def run_cli(mode: str) -> None:
    from shared.models import RunConfig
    from shared.vc_profile import load_profile
    from orchestration.events import get_bus
    from orchestration.pipeline import PipelineRunner
    from orchestration.autonomous import run_autonomous

    profile = load_profile()
    bus = get_bus()
    runner = PipelineRunner(bus)
    config = RunConfig(mode=mode)  # type: ignore[arg-type]

    print(f"→ Running {mode} mode with saved VC profile")
    if mode == "autonomous":
        await run_autonomous(runner, profile, config)
    else:
        await runner.run_once(profile, config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Research Intelligence Pipeline")
    parser.add_argument(
        "--cli", choices=["single", "autonomous"],
        help="Skip the GUI and run directly from the saved VC profile.",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Start the server without opening a browser window.",
    )
    args = parser.parse_args()

    if args.cli:
        try:
            asyncio.run(run_cli(args.cli))
        except KeyboardInterrupt:
            print("\n→ Cancelled.")
            sys.exit(130)
        return

    serve(open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
