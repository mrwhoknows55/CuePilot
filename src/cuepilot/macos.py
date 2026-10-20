"""macOS menu bar frontend for CuePilot."""

import rumps


class CuePilotMenuBar(rumps.App):
    def __init__(self) -> None:
        super().__init__("CuePilot", menu=["About CuePilot"], quit_button="Quit CuePilot")

    @rumps.clicked("About CuePilot")
    def show_about(self, _: rumps.MenuItem) -> None:
        rumps.alert(
            "CuePilot",
            "Always ready in your menu bar. Just speak naturally, and CuePilot "
            "quickly takes action on your Mac, right on your device.",
        )


def run() -> None:
    CuePilotMenuBar().run()
