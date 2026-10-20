"""Route addressed speech through local Laya to parameterized Mac actions."""

import json
import logging
import math
import os
import re
import subprocess
from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event, Thread
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from cuepilot.applications import resolve_application
from cuepilot.config import WAKE_WORD, WAKE_WORD_ALIASES

logger = logging.getLogger(__name__)

ENDPOINT = "http://localhost:8888/v1/systemone"
MIN_PROBABILITY = 0.85
# Each action has a description for Laya, a fixed script, and a success message.
ACTIONS = {
    "open_app": (
        "Open or switch to the explicitly named installed application",
        "on run argv\nset appPath to item 1 of argv\ntell application appPath to activate\nend run",
        "Opened application",
    ),
    "open_website": (
        "Open Chrome and visit a website",
        """on run argv
tell application id "com.google.Chrome"
    if (count of windows) is 0 then make new window
    make new tab at end of tabs of window 1 with properties {URL:item 1 of argv}
    activate
end tell
end run""",
        "Opened website in Chrome",
    ),
    "mute": (
        "Mute the Mac's audio output",
        "set volume output muted true",
        "Sound muted",
    ),
    "unmute": (
        "Unmute the Mac's audio output",
        "set volume output muted false",
        "Sound unmuted",
    ),
    "volume_up": (
        "Increase the Mac's sound output volume",
        """set level to (output volume of (get volume settings)) + 10
if level > 100 then set level to 100
set volume output volume level output muted (level is 0)""",
        "Volume increased",
    ),
    "volume_down": (
        "Decrease the Mac's sound output volume",
        """set level to (output volume of (get volume settings)) - 10
if level < 0 then set level to 0
set volume output volume level output muted (level is 0)""",
        "Volume decreased",
    ),
    "volume_set": (
        "Set the Mac's sound output volume to the specified percentage",
        """on run argv
set level to (item 1 of argv) as integer
if level < 0 or level > 100 then error "Volume must be between 0 and 100"
set volume output volume level output muted (level is 0)
end run""",
        "Volume updated",
    ),
    "spotify_play": (
        "Play or resume music in Spotify",
        'tell application id "com.spotify.client" to play',
        "Resumed Spotify",
    ),
    "spotify_pause": (
        "Pause music in Spotify",
        'tell application id "com.spotify.client" to pause',
        "Paused Spotify",
    ),
    "spotify_next": (
        "Skip to the next song or track in Spotify",
        'tell application id "com.spotify.client" to next track',
        "Next Spotify track",
    ),
    "spotify_previous": (
        "Go to the previous song or track in Spotify",
        'tell application id "com.spotify.client" to previous track',
        "Previous Spotify track",
    ),
    "brightness_up": (
        "Increase display brightness",
        'tell application "System Events" to key code 144',
        "Requested brightness increase",
    ),
    "brightness_down": (
        "Decrease display brightness",
        'tell application "System Events" to key code 145',
        "Requested brightness decrease",
    ),
}
_wake_names = "|".join(
    r"\s+".join(re.escape(part) for part in name.split())
    for name in sorted((WAKE_WORD, *WAKE_WORD_ALIASES), key=len, reverse=True)
)
ADDRESS = re.compile(rf"^\s*(?:{_wake_names})\b[\s,.:!—-]*", re.IGNORECASE)
COMMAND_PATTERNS = {
    "mute": r"mute(?: (?:the )?(?:sound|audio|volume))?",
    "unmute": r"unmute(?: (?:the )?(?:sound|audio|volume))?",
    "volume_up": r"(?:(?:increase|raise|turn up) (?:the )?volume|volume up|turn (?:the )?volume up)",
    "volume_down": r"(?:(?:decrease|lower|reduce|turn down) (?:the )?volume|volume down|turn (?:the )?volume down)",
    "spotify_play": r"(?:play|resume)(?: (?:music|song|playback|spotify))?(?: (?:on|in) spotify)?",
    "spotify_pause": r"pause(?: (?:music|song|playback|spotify))?(?: (?:on|in) spotify)?",
    "spotify_next": r"(?:next|skip)(?: (?:song|track))?(?: (?:on|in) spotify)?",
    "spotify_previous": r"(?:previous|prev)(?: (?:song|track))?(?: (?:on|in) spotify)?",
    "brightness_up": r"(?:(?:increase|raise|turn up) (?:the )?brightness|brightness up|(?:make (?:the )?(?:screen|display) )?brighter)",
    "brightness_down": r"(?:(?:decrease|lower|reduce|turn down) (?:the )?brightness|brightness down|(?:make (?:the )?(?:screen|display) )?dimmer)",
}


@dataclass(frozen=True)
class Command:
    action: str
    arguments: tuple[str, ...] = ()
    message: str = ""


def website_url(text: str) -> str:
    url = re.sub(r"\s+dot\s+", ".", text.strip(), flags=re.IGNORECASE)
    if "://" not in url:
        url = "https://" + url
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or re.search(r'[\s<>"\\\x00-\x1f]', url)
        or not re.fullmatch(
            r"(?:[a-zA-Z0-9-]+\.)+[a-zA-Z0-9-]+|localhost", parsed.hostname
        )
    ):
        raise ValueError("Please say a website address, such as github.com")
    # Accessing port also validates its numeric range.
    parsed.port
    return url


def prepare(text: str) -> Command | None:
    text = " ".join(text.split()).strip(" .!?")
    text = re.sub(
        r"^(?:please |(?:can|could|would) you (?:please )?)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r" please$", "", text, flags=re.IGNORECASE)
    volume = re.fullmatch(
        r"(?:set (?:the )?)?volume (?:to )?(-?\d+)\s*(?:percent|%)?",
        text, flags=re.IGNORECASE,
    )
    if volume:
        level = int(volume[1])
        if not 0 <= level <= 100:
            raise ValueError("Volume must be between 0 and 100 percent")
        return Command("volume_set", (str(level),), f"Volume set to {level}%")
    for action, pattern in COMMAND_PATTERNS.items():
        if re.fullmatch(pattern, text, flags=re.IGNORECASE):
            if action.startswith("spotify_"):
                resolve_application("Spotify")
            return Command(action)
    browser = re.fullmatch(
        r"(?:open|launch) (?:google )?chrome (?:and (?:then )?|then )(?:open |go to |visit )?(.+)",
        text,
        flags=re.IGNORECASE,
    ) or re.fullmatch(
        r"(?:open|visit) (.+) in (?:google )?chrome", text, flags=re.IGNORECASE
    )
    if browser:
        resolve_application("Google Chrome")
        return Command("open_website", (website_url(browser[1]),))
    opening = re.fullmatch(
        r"(?:open|launch|switch to|activate) (.+)", text, flags=re.IGNORECASE
    )
    if opening:
        # Only one app per request; never interpret a compound request as an app.
        if re.search(r"\b(?:and|then)\b", opening[1], flags=re.IGNORECASE):
            return None
        app = resolve_application(opening[1])
        return Command("open_app", (app.path,), f"Opened {app.name}")
    return None


def decide(text: str) -> Command | None:
    """Return a supported action only when Laya is sufficiently certain."""
    # Laya can confidently misroute negations, unsupported apps, and conversation.
    command = prepare(text)
    if command is None:
        return None
    # Supply the resolved capability, not every installed app or unrelated action.
    description = ACTIONS[command.action][0]
    if command.action == "open_app":
        description += f": {command.arguments[0]}"
    elif command.action == "open_website":
        description = f"Open Chrome and go to the website {command.arguments[0]}"
    elif command.action == "volume_set":
        description = f"Set sound output volume to {command.arguments[0]} percent"
    criteria = {command.action: description}
    criteria["ignore"] = (
        "Conversation, questions, negated requests, or unsupported actions"
    )
    instructions = (
        "Select the single action explicitly requested by the speaker. "
        "Choose ignore if no single supported action is requested."
    )
    if command.action == "open_website":
        # This capability includes launching the browser and navigating together.
        instructions = "Which action is requested?"
        criteria["ignore"] = "No action requested"
    payload = {
        "model": "laya",
        "state": text,
        "questions": {
            "action": {
                "type": "choice",
                "instructions": instructions,
                "criteria": criteria,
            }
        },
    }
    headers = {"Content-Type": "application/json"}
    if key := os.environ.get("CUEPILOT_LAYA_API_KEY"):
        headers["Authorization"] = f"Bearer {key}"
    request = Request(ENDPOINT, data=json.dumps(payload).encode(), headers=headers)
    with urlopen(request, timeout=30) as response:
        answer = json.load(response)["answers"]["action"]
    choice = answer["choice"]
    probability = answer["probabilities"][choice]
    if (
        type(probability) not in (int, float)
        or not math.isfinite(probability)
        or not 0 <= probability <= 1
    ):
        raise ValueError("Laya returned an invalid action probability")
    if choice != command.action or probability < MIN_PROBABILITY:
        logger.info(
            "Command declined by Laya: expected=%s selected=%s probability=%.3f",
            command.action, choice, probability,
        )
        return None
    return command


class CommandProcessor:
    """Keep HTTP and AppleScript execution off the microphone and UI threads."""

    def __init__(self) -> None:
        self._pending: Queue[tuple[int, str]] = Queue(maxsize=2)
        self._messages: Queue[tuple[int, str]] = Queue()
        self._generation = 0
        self._stop = Event()
        self._thread = Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def submit(self, transcript: str) -> bool:
        match = ADDRESS.match(transcript)
        if not match or self._stop.is_set():
            return False
        text = transcript[match.end() :].strip()
        if not text:
            return False
        try:
            self._pending.put_nowait((self._generation, text))
            logger.info("Command queued: %s", text)
        except Full:
            logger.warning("Command queue full; please try again")
            self._messages.put((self._generation, "Busy — please try again"))
        return True

    def reset(self) -> None:
        """Invalidate queued requests and results, including an in-flight decision."""
        self._generation += 1
        while True:
            try:
                self._pending.get_nowait()
            except Empty:
                break

    def poll(self) -> list[str]:
        messages = []
        while True:
            try:
                generation, message = self._messages.get_nowait()
            except Empty:
                return messages
            if generation == self._generation:
                messages.append(message)

    def close(self) -> None:
        self._stop.set()
        self.reset()
        if self._thread.is_alive():
            self._thread.join(timeout=1)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                generation, text = self._pending.get(timeout=0.1)
            except Empty:
                continue
            if generation != self._generation:
                continue
            try:
                command = decide(text)
                if self._stop.is_set() or generation != self._generation:
                    continue
                if command is None:
                    logger.info("Command skipped: unsupported or uncertain request")
                    self._messages.put((generation, "Please try a supported command"))
                    continue
                _, script, message = ACTIONS[command.action]
                message = command.message or message
                subprocess.run(
                    ["/usr/bin/osascript", "-e", script, *command.arguments],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                logger.info("Command completed: %s", command.action)
            except ValueError as exc:
                logger.warning("Command rejected: %s", exc)
                message = str(exc)
            except subprocess.CalledProcessError as exc:
                logger.warning("AppleScript failed: %s", exc.stderr.strip())
                message = (
                    "Couldn’t run command — check Automation/Accessibility permissions"
                )
            except subprocess.TimeoutExpired:
                logger.warning("AppleScript command timed out")
                message = "Command timed out"
            except Exception:
                logger.exception("Could not process command")
                message = "Couldn’t process command — check local Laya server"
            self._messages.put((generation, message))
