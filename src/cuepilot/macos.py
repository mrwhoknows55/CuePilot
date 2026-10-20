"""macOS menu bar frontend for CuePilot."""

import logging
from importlib.metadata import version

import rumps
import sounddevice as sd
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

from cuepilot.microphone import Microphone

logger = logging.getLogger(__name__)


class CuePilotMenuBar(rumps.App):
    def __init__(self) -> None:
        super().__init__("CuePilot", quit_button="Quit CuePilot")
        self._about_window = None
        self.microphone = Microphone()
        self._reported_audio = False
        self._last_audio_error = None
        self._reported_silence = False
        self.mic_status = rumps.MenuItem("Microphone: Starting")
        self.mic_status.set_callback(None)
        self.input_level = rumps.MenuItem("Input level: --")
        self.input_level.set_callback(None)
        self.mic_toggle = rumps.MenuItem("Pause Microphone", callback=self.toggle_microphone)
        self.menu = [
            self.mic_status,
            self.input_level,
            self.mic_toggle,
            None,
            rumps.MenuItem("About CuePilot", callback=self.show_about),
        ]

    def start_microphone(self) -> None:
        try:
            self.microphone.start()
        except (sd.PortAudioError, OSError) as exc:
            logger.error("Could not start microphone: %s", exc)
            self.mic_status.title = "Microphone: Unavailable"
            self.input_level.title = "Input level: --"
            self.mic_toggle.title = "Retry Microphone"
            return
        self._reported_audio = False
        self._last_audio_error = None
        self._reported_silence = False
        self.mic_status.title = "Microphone: Listening"
        self.mic_toggle.title = "Pause Microphone"
        logger.info(
            "Listening on %s at %d Hz (mono, 16-bit)",
            self.microphone.device_name,
            self.microphone.sample_rate,
        )

    def toggle_microphone(self, _: rumps.MenuItem) -> None:
        if self.microphone.active:
            self.microphone.stop()
            self.mic_status.title = "Microphone: Paused"
            self.input_level.title = "Input level: --"
            self.mic_toggle.title = "Resume Microphone"
            logger.info("Microphone paused")
        else:
            self.start_microphone()

    def refresh_microphone(self) -> None:
        if not self.microphone.active:
            if self.mic_status.title == "Microphone: Listening":
                self.mic_status.title = "Microphone: Stopped"
                self.mic_toggle.title = "Retry Microphone"
                logger.error("Microphone stream stopped unexpectedly")
            return
        if self.microphone.frames_received and not self._reported_audio:
            logger.info("Microphone stream is delivering audio frames")
            self._reported_audio = True
        self.input_level.title = f"Input level: {self.microphone.take_peak():.0%}"
        if (
            not self.microphone.has_signal
            and self.microphone.frames_received >= 5 * self.microphone.sample_rate
        ):
            self.mic_status.title = "Microphone: No input signal"
            if not self._reported_silence:
                logger.warning("No microphone signal; check input device or macOS permission")
                self._reported_silence = True
        elif self.microphone.has_signal and self._reported_silence:
            self.mic_status.title = "Microphone: Listening"
            self._reported_silence = False
            logger.info("Microphone signal detected")
        if self.microphone.error and self.microphone.error != self._last_audio_error:
            logger.warning("Microphone: %s", self.microphone.error)
            self._last_audio_error = self.microphone.error

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
        app.start_microphone()

    @rumps.timer(1)
    def update_microphone(_timer) -> None:
        app.refresh_microphone()

    @rumps.events.before_quit
    def quitting() -> None:
        app.microphone.stop()
        logger.info("Quitting CuePilot")

    logger.info("Starting CuePilot")
    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyAccessory
    )
    app.run()
