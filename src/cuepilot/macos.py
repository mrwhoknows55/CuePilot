"""macOS menu bar frontend for CuePilot."""

import logging
from importlib.metadata import version

import rumps
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSColor,
    NSFont,
    NSImage,
    NSImageView,
    NSMakeRect,
    NSTextField,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)

logger = logging.getLogger(__name__)


class CuePilotMenuBar(rumps.App):
    def __init__(self) -> None:
        super().__init__("CuePilot", quit_button="Quit CuePilot")
        self._about_window = None
        self.menu = [rumps.MenuItem("About CuePilot", callback=self.show_about)]

    def show_about(self, _: rumps.MenuItem) -> None:
        logger.info("Opening About CuePilot")
        if self._about_window is None:
            self._about_window = self._make_about_window()
        NSApplication.sharedApplication().activate()
        self._about_window.makeKeyAndOrderFront_(None)
        self._about_window.orderFrontRegardless()

    def _make_about_window(self) -> NSWindow:
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 430, 220),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        window.setTitle_("About CuePilot")
        window.setReleasedWhenClosed_(False)
        window.center()
        content = window.contentView()

        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "waveform", "Voice"
        )
        if image is not None:
            icon = NSImageView.alloc().initWithFrame_(NSMakeRect(28, 145, 48, 48))
            icon.setImage_(image)
            content.addSubview_(icon)

        def add_label(text: str, frame, font, color=None) -> None:
            label = NSTextField.labelWithString_(text)
            label.setFrame_(frame)
            label.setFont_(font)
            if color is not None:
                label.setTextColor_(color)
            content.addSubview_(label)

        add_label(
            "CuePilot", NSMakeRect(94, 163, 310, 32), NSFont.boldSystemFontOfSize_(24)
        )
        add_label(
            "Always ready in your menu bar",
            NSMakeRect(94, 140, 310, 22),
            NSFont.systemFontOfSize_(13),
            NSColor.secondaryLabelColor(),
        )
        add_label(
            "Speak naturally to get things done on your Mac.",
            NSMakeRect(28, 91, 380, 24),
            NSFont.systemFontOfSize_(13),
        )
        add_label(
            "Designed for fast, private processing on Apple Silicon.",
            NSMakeRect(28, 65, 380, 24),
            NSFont.systemFontOfSize_(13),
        )
        add_label(
            f"Version {version('cuepilot')}",
            NSMakeRect(28, 24, 380, 20),
            NSFont.systemFontOfSize_(11),
            NSColor.secondaryLabelColor(),
        )
        return window


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    app = CuePilotMenuBar()

    @rumps.events.before_start
    def menu_ready() -> None:
        # Keep the normal menu and also expose it as the button's context menu.
        app._nsapp.nsstatusitem.button().setMenu_(app.menu._menu)
        logger.info("Menu bar ready; left or right click CuePilot to open its menu")

    @rumps.events.before_quit
    def quitting() -> None:
        logger.info("Quitting CuePilot")

    logger.info("Starting CuePilot")
    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyAccessory
    )
    app.run()
