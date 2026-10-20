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
from Foundation import NSLocale

from cuepilot.microphone import Microphone
from cuepilot.transcription import SpeechTranscriber

logger = logging.getLogger(__name__)


class CuePilotMenuBar(rumps.App):
    def __init__(self) -> None:
        super().__init__("CuePilot", quit_button="Quit CuePilot")
        self._about_window = None
        self.transcriber = SpeechTranscriber()
        self.microphone = Microphone(on_chunk=self.transcriber.feed)
        preferred = NSLocale.preferredLanguages()
        self.system_language = (
            str(preferred[0]).replace("_", "-").split("-")[0].lower()
            if preferred
            else "en"
        )
        self._model_ready = False
        self._model_error = False
        self._paused = False
        self._reported_audio = False
        self._last_audio_error = None
        self._reported_silence = False
        self.mic_status = rumps.MenuItem("Getting ready…")
        self.mic_status.set_callback(None)
        self.last_transcript = rumps.MenuItem("No transcript yet")
        self.last_transcript.set_callback(None)
        self.english_language = rumps.MenuItem("English")
        self.english_language.state = True
        self.system_language_name = str(
            NSLocale.currentLocale().localizedStringForLanguageCode_(self.system_language)
            or self.system_language.upper()
        )
        self.system_language_item = rumps.MenuItem(
            f"System Default — {self.system_language_name}"
        )
        self.language_menu = rumps.MenuItem("Language: English")
        self.language_menu.update([self.english_language, self.system_language_item])
        self.mic_toggle = rumps.MenuItem("Pause Microphone", callback=self.toggle_microphone)
        self.menu = [
            self.mic_status,
            self.last_transcript,
            None,
            self.mic_toggle,
            self.language_menu,
            None,
            rumps.MenuItem("About CuePilot", callback=self.show_about),
        ]

    def start_microphone(self) -> None:
        self._paused = False
        try:
            self.microphone.start()
        except (sd.PortAudioError, OSError) as exc:
            logger.error("Could not start microphone: %s", exc)
            self._refresh_status()
            return
        self._reported_audio = False
        self._last_audio_error = None
        self._reported_silence = False
        self._refresh_status()
        logger.info(
            "Listening on %s at %d Hz (mono, 16-bit)",
            self.microphone.device_name,
            self.microphone.sample_rate,
        )

    def toggle_microphone(self, _: rumps.MenuItem) -> None:
        if self.microphone.active:
            self._paused = True
            self.microphone.stop()
            self.transcriber.reset()
            self._refresh_status()
            logger.info("Microphone paused")
        else:
            self.start_microphone()

    def use_english(self, _: rumps.MenuItem) -> None:
        if self.transcriber.language != "en":
            self.transcriber.set_language("en")
        self.english_language.state = True
        self.system_language_item.state = False
        self.language_menu.title = "Language: English"
        logger.info("Transcription language: English")

    def use_system_language(self, _: rumps.MenuItem) -> None:
        if self.transcriber.language != self.system_language:
            self.transcriber.set_language(self.system_language)
        self.english_language.state = False
        self.system_language_item.state = True
        self.language_menu.title = f"Language: {self.system_language_name} (System)"
        logger.info("Transcription language: system (%s)", self.system_language)

    def _refresh_status(self) -> None:
        if self._paused:
            status = "Paused"
            action = "Resume Microphone"
        elif not self.microphone.active:
            status = "Microphone unavailable"
            action = "Retry Microphone"
        else:
            action = "Pause Microphone"
            if self._model_error:
                status = "Transcription unavailable"
            elif not self._model_ready:
                status = "Getting ready…"
            elif self._reported_silence:
                status = "No microphone input"
            else:
                status = "Listening"
        self.mic_status.title = status
        self.mic_toggle.title = action

    def refresh_microphone(self) -> None:
        for kind, value in self.transcriber.poll():
            if kind == "ready":
                self._model_ready = True
                self._model_error = False
                self.english_language.set_callback(self.use_english)
                if self.system_language in self.transcriber.supported_languages:
                    self.system_language_item.set_callback(self.use_system_language)
                else:
                    self.system_language_item.title = (
                        f"System Default — {self.system_language_name} (Unavailable)"
                    )
                    logger.warning(
                        "Whisper does not support system language %s; using English",
                        self.system_language,
                    )
                logger.info("Whisper model ready: %s", value)
            elif kind == "transcript":
                preview = " ".join(value.split())
                if len(preview) > 60:
                    preview = preview[:59].rstrip() + "…"
                self.last_transcript.title = f"“{preview}”"
                self._model_error = False
                logger.info("Transcript: %s", value)
            elif kind == "error":
                self._model_error = True
                logger.error("%s", value)
        if self.transcriber.dropped_audio:
            logger.warning("Audio chunks dropped while transcription was busy")
            self.transcriber.dropped_audio = False
        if not self.microphone.active:
            self._refresh_status()
            return
        if self.microphone.frames_received and not self._reported_audio:
            logger.info("Microphone stream is delivering audio frames")
            self._reported_audio = True
        if (
            not self.microphone.has_signal
            and self.microphone.frames_received >= 5 * self.microphone.sample_rate
        ):
            if not self._reported_silence:
                logger.warning("No microphone signal; check input device or macOS permission")
                self._reported_silence = True
        elif self.microphone.has_signal and self._reported_silence:
            self._reported_silence = False
            logger.info("Microphone signal detected")
        if self.microphone.error and self.microphone.error != self._last_audio_error:
            logger.warning("Microphone: %s", self.microphone.error)
            self._last_audio_error = self.microphone.error
        self._refresh_status()

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

    import atexit
    import signal
    import sys

    shutdown_complete = False

    def _shutdown() -> None:
        nonlocal shutdown_complete
        if shutdown_complete:
            return
        shutdown_complete = True
        try:
            app.microphone.stop()
        except Exception as exc:
            logger.debug("Microphone stop failed during shutdown: %s", exc)
        try:
            app.transcriber.close()
        except Exception as exc:
            logger.debug("Transcriber close failed during shutdown: %s", exc)

    def _handle_term(_signum, _frame) -> None:
        _shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_term)
    signal.signal(signal.SIGINT, _handle_term)
    atexit.register(_shutdown)

    @rumps.events.before_start
    def menu_ready() -> None:
        # Keep the normal menu and also expose it as the button's context menu.
        app._nsapp.nsstatusitem.button().setMenu_(app.menu._menu)
        logger.info("Menu bar ready; left or right click CuePilot to open its menu")
        app.transcriber.start()
        app.start_microphone()

    @rumps.timer(1)
    def update_microphone(_timer) -> None:
        app.refresh_microphone()

    @rumps.events.before_quit
    def quitting() -> None:
        _shutdown()
        logger.info("Quitting CuePilot")

    logger.info("Starting CuePilot")
    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyAccessory
    )
    app.run()
