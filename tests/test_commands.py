import io
import json
import unittest
from threading import Event
from unittest.mock import patch

from cuepilot.applications import Application
from cuepilot.commands import (
    ACTIONS,
    Command,
    CommandProcessor,
    decide,
    prepare,
    website_url,
)
from cuepilot.config import WAKE_WORD, WAKE_WORD_ALIASES


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.apps = patch(
            "cuepilot.commands.resolve_application",
            return_value=Application(
                "Notes", "/System/Applications/Notes.app", "com.apple.Notes"
            ),
        )
        self.apps.start()
        self.addCleanup(self.apps.stop)

    def response(self, choice="mute", probability=0.95, confidence=0.01):
        return io.StringIO(
            json.dumps(
                {
                    "answers": {
                        "action": {
                            "choice": choice,
                            "confidence": confidence,
                            "probabilities": {choice: probability},
                        }
                    }
                }
            )
        )

    def test_local_request_and_probability_not_confidence(self):
        with (
            patch("cuepilot.commands.urlopen", return_value=self.response()) as send,
            patch.dict("os.environ", {"CUEPILOT_LAYA_API_KEY": ""}),
        ):
            self.assertEqual(decide("mute"), Command("mute"))
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:8888/v1/systemone")
        self.assertIsNone(request.get_header("Authorization"))
        payload = json.loads(request.data)
        self.assertEqual(payload["state"], "mute")
        self.assertEqual(payload["model"], "laya")
        self.assertIn("ignore", payload["questions"]["action"]["criteria"])

    def test_rejects_uncertain_ignored_and_unknown_actions(self):
        for choice, probability in [("mute", 0.84), ("ignore", 1), ("delete_files", 1)]:
            with (
                self.subTest(choice=choice),
                patch(
                    "cuepilot.commands.urlopen",
                    return_value=self.response(choice, probability, 1),
                ),
            ):
                self.assertIsNone(decide("mute"))

    def test_invalid_probabilities_fail(self):
        for probability in [True, "0.99", -1, 2, float("nan"), float("inf")]:
            with (
                self.subTest(probability=probability),
                patch(
                    "cuepilot.commands.urlopen",
                    return_value=self.response(probability=probability),
                ),
                self.assertRaises(ValueError),
            ):
                decide("mute")

    def test_optional_authentication(self):
        with (
            patch.dict("os.environ", {"CUEPILOT_LAYA_API_KEY": "test-key"}),
            patch("cuepilot.commands.urlopen", return_value=self.response()) as send,
        ):
            decide("mute")
        self.assertEqual(
            send.call_args.args[0].get_header("Authorization"), "Bearer test-key"
        )

    def test_unsupported_and_negated_commands_do_not_reach_model(self):
        with patch("cuepilot.commands.urlopen") as send:
            for text in [
                "Do not open Safari",
                "Don't mute",
                "Don’t unmute",
                "Never open Notes",
                "Cancel that",
                "Open Safari and mute",
                "I was reading about Safari",
            ]:
                self.assertIsNone(decide(text))
            send.assert_not_called()

    def test_wrong_supported_action_is_rejected(self):
        with patch("cuepilot.commands.urlopen", return_value=self.response("mute")):
            self.assertIsNone(decide("open Notes"))


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.lookup = patch(
            "cuepilot.commands.resolve_application",
            return_value=Application(
                "Google Chrome", "/Applications/Google Chrome.app", "com.google.Chrome"
            ),
        )
        self.lookup.start()
        self.addCleanup(self.lookup.stop)

    def test_dynamic_app_arguments(self):
        self.assertEqual(
            prepare("Please open Chrome"),
            Command(
                "open_app", ("/Applications/Google Chrome.app",), "Opened Google Chrome"
            ),
        )

    def test_browser_sequence(self):
        for text in [
            "open chrome and then github.com",
            "open Chrome and then go to github.com",
            "open github.com in Chrome",
        ]:
            self.assertEqual(
                prepare(text), Command("open_website", ("https://github.com",))
            )

    def test_website_validation(self):
        self.assertEqual(website_url("github dot com"), "https://github.com")
        for url in [
            "javascript:alert(1)",
            "file:///etc/passwd",
            "https://user:pass@example.com",
            "https://example.com/ bad",
            'https://example.com/"',
            "https://example.com:99999",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                website_url(url)

    def test_media_and_brightness(self):
        for text, action in [
            ("pause song", "spotify_pause"),
            ("resume spotify", "spotify_play"),
            ("next song", "spotify_next"),
            ("prev track", "spotify_previous"),
            ("increase brightness", "brightness_up"),
            ("make the screen dimmer", "brightness_down"),
        ]:
            self.assertEqual(prepare(text), Command(action))

    def test_relative_volume(self):
        for text, action in [
            ("volume up", "volume_up"),
            ("increase the volume", "volume_up"),
            ("turn the volume up", "volume_up"),
            ("volume down", "volume_down"),
            ("lower volume", "volume_down"),
            ("turn the volume down", "volume_down"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(prepare(text), Command(action))

    def test_exact_volume(self):
        for text, level in [
            ("set volume to 40 percent", 40),
            ("volume 50%", 50),
            ("please set the volume to 0", 0),
            ("set volume to 100 percent", 100),
        ]:
            with self.subTest(text=text):
                self.assertEqual(prepare(text), Command(
                    "volume_set", (str(level),), f"Volume set to {level}%"
                ))

    def test_invalid_volume(self):
        for text in ["set volume to 101", "volume -1", "volume 999"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                prepare(text)
        for text in ["do not increase volume", "set volume to 40 and open Safari", "volume 40; do shell script"]:
            with self.subTest(text=text):
                self.assertIsNone(prepare(text))

    def test_missing_application(self):
        with (
            patch(
                "cuepilot.commands.resolve_application",
                side_effect=ValueError("Not installed"),
            ),
            self.assertRaises(ValueError),
        ):
            prepare("open missing app")


class CommandTests(unittest.TestCase):
    def test_configured_wake_word(self):
        for name in (WAKE_WORD, *WAKE_WORD_ALIASES):
            with self.subTest(name=name):
                commands = CommandProcessor()
                self.assertTrue(commands.submit(f"{name} open chrome"))
                self.assertEqual(commands._pending.get_nowait(), (0, "open chrome"))

    def test_requires_address_and_nonempty_command(self):
        commands = CommandProcessor()
        for text in [
            "open Safari",
            "I mentioned CuePilot",
            "CuePilot",
            "CuePilotage mute",
            "Cue",
            "Queueball open Chrome",
            "Cueball open Chrome",
        ]:
            self.assertFalse(commands.submit(text))
        self.assertTrue(commands.submit("Cue Pilot, open Safari"))
        self.assertEqual(commands._pending.get_nowait(), (0, "open Safari"))

    def test_short_wake_name(self):
        for text in ["Cue open chrome", "Cue, open chrome", "cue: open chrome", "CuePilot open chrome", "Cue Pilot open chrome"]:
            with self.subTest(text=text):
                commands = CommandProcessor()
                self.assertTrue(commands.submit(text))
                self.assertEqual(commands._pending.get_nowait(), (0, "open chrome"))

    def test_queue_is_bounded_and_reset_discards_old_results(self):
        commands = CommandProcessor()
        for _ in range(3):
            commands.submit("CuePilot mute")
        self.assertEqual(commands._pending.qsize(), 2)
        self.assertEqual(commands.poll(), ["Busy — please try again"])
        commands._messages.put((0, "old result"))
        commands.reset()
        self.assertTrue(commands._pending.empty())
        self.assertEqual(commands.poll(), [])

    def test_executes_only_fixed_script(self):
        commands = CommandProcessor()
        with (
            patch("cuepilot.commands.decide", return_value=Command("mute")),
            patch("cuepilot.commands.subprocess.run") as run,
        ):
            commands.start()
            try:
                commands.submit("CuePilot mute")
                self.assertEqual(commands._messages.get(timeout=2), (0, "Sound muted"))
                self.assertEqual(
                    run.call_args.args[0],
                    ["/usr/bin/osascript", "-e", ACTIONS["mute"][1]],
                )
            finally:
                commands.close()

    def test_pause_during_request_prevents_execution(self):
        entered, release, finished = Event(), Event(), Event()

        def delayed_decision(text):
            entered.set()
            release.wait(timeout=2)
            finished.set()
            return Command("mute")

        commands = CommandProcessor()
        with (
            patch("cuepilot.commands.decide", side_effect=delayed_decision),
            patch("cuepilot.commands.subprocess.run") as run,
        ):
            commands.start()
            try:
                commands.submit("CuePilot mute")
                self.assertTrue(entered.wait(timeout=2))
                commands.reset()
                release.set()
                self.assertTrue(finished.wait(timeout=2))
            finally:
                release.set()
                commands.close()
            run.assert_not_called()

    def test_server_failure_keeps_worker_alive(self):
        commands = CommandProcessor()
        with (
            patch(
                "cuepilot.commands.decide",
                side_effect=[OSError("offline"), Command("mute")],
            ),
            patch("cuepilot.commands.subprocess.run") as run,
        ):
            commands.start()
            try:
                with self.assertLogs("cuepilot.commands", level="ERROR"):
                    commands.submit("CuePilot mute")
                    self.assertIn(
                        "check local Laya server", commands._messages.get(timeout=2)[1]
                    )
                commands.submit("CuePilot mute")
                self.assertEqual(commands._messages.get(timeout=2), (0, "Sound muted"))
                run.assert_called_once()
            finally:
                commands.close()


if __name__ == "__main__":
    unittest.main()
