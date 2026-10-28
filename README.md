# CuePilot

A macOS menu bar application managed as a Python 3.14 uv workspace.

```text
.
├── pyproject.toml          # Root application and workspace configuration
├── uv.lock                 # Shared dependency lockfile
├── src/cuepilot/           # Entry point and platform frontends
└── packages/               # Shared libraries when needed
```

## Development

From the repository root:

```sh
uv sync --locked --all-packages
uv run cuepilot
```

On macOS, CuePilot appears in the menu bar and starts listening to the default
microphone. Left or right click it to see the current status and latest
transcript, choose English or the Mac's first preferred system language, pause or
resume capture, open About, or quit. English is selected by default. The terminal
logs the input device, sample rate, and recognized speech. CuePilot groups speech
using Silero VAD and a short silence gap, then transcribes it locally with MLX
Whisper. The first launch downloads the `mlx-community/whisper-tiny` model; later
launches use the local cache.
If the model does not support the system language, its menu option is disabled.

macOS may ask for microphone access. If the menu reports **No microphone input**,
check **System Settings → Privacy & Security → Microphone** for the terminal
running CuePilot, then check the selected device under **Sound → Input**.
CuePilot keeps live audio and transcripts in memory. It does not save recordings
or send microphone audio to a service. The capture code emits 20 ms mono PCM
chunks; a dedicated worker groups them before transcription. Supported requests
send transcript text to your local Laya server as described below.

## Local voice commands

Start Unsloth Studio in a separate terminal and keep it running:

```sh
unsloth studio -H 127.0.0.1 -p 8888
```

Open `http://localhost:8888` and enable the Decision API in **Settings → API**
with the Laya model enabled. See the [Unsloth Decision API setup](https://unsloth.ai/docs/basics/train-your-own-decision-model-with-unsloth).
CuePilot connects to `http://localhost:8888/v1/systemone` by default. If the
server uses a different address or port, set `CUEPILOT_LAYA_ENDPOINT` to its full
Decision API URL before starting CuePilot. A connection-refused message means
the server is not listening at that address; commands will not execute until
it is available. CuePilot reports the connection problem and accepts subsequent
commands once the server is running.

Keyless localhost access works by default. If your server
requires authentication, set `CUEPILOT_LAYA_API_KEY` before running CuePilot.
No additional Python dependencies or local model downloads are needed for Laya.

Say one command at a time, such as “open Chrome.” No wake word is required.
Silero VAD detects speech locally in 32 ms windows; after about half a second of
silence, Whisper transcribes the segment and CuePilot checks it for a supported
command. The Silero model is bundled with the installed package. Examples:

- “open Safari.”
- “open Notes.”
- “open Finder.”
- “open Chrome.”
- “open Chrome and then github.com.”
- “open youtube.com in Chrome.”
- “open Spotify.”
- “next song.”
- “pause music.”
- “resume Spotify.”
- “previous song.”
- “increase brightness.”
- “decrease brightness.”
- “mute.”
- “unmute.”
- “volume up.”
- “volume down.”
- “set volume to 40 percent.”

Volume up/down adjusts system output by 10 percentage points, clamped to 0–100.
Exact volume accepts an integer percentage in that range. Positive changes
unmute output; zero mutes it. This controls system volume, not Spotify's separate
volume slider. Some digital/external output devices do not support system volume.

CuePilot checks each transcript and sends supported requests to Laya using
`model: "laya"` and a resolved capability and its parameters plus an `ignore`
choice. It executes a predefined
AppleScript only when the chosen action's probability is at least 0.85. This
initial threshold is a heuristic, not a guarantee of correct classification.
Speech that does not match a supported request does not trigger commands. The
menu shows command results; the terminal logs detailed errors. macOS may ask for Automation
permission to control an app.

App opening is generic: CuePilot discovers application bundles in `/Applications`,
`~/Applications`, and `/System/Applications`, including their subfolders, plus
Finder. It reads app names and bundle identifiers through `NSBundle`. Chrome is
an alias for Google Chrome. The discovery cache lasts until CuePilot restarts;
apps in other folders are not included. Ambiguous names require the full app name.

This first version accepts simple English requests, optionally with “please” or
“can/could/would you.” Negations, conversation, and arbitrary command sequences
are rejected before classification. Opening Chrome and a website together is a
supported combined capability. Websites must be HTTP(S) domain addresses; “dot”
is accepted between domain labels. URLs and app paths are passed as script
arguments, never interpolated into script source.
Laya must agree with the explicitly named action. Whisper's language menu still
controls transcription; multilingual command execution is not supported yet.

Playback controls target the installed Spotify desktop app. Start playing a
playlist manually before testing next, previous, pause, and resume. They do not
control a Spotify browser tab or other media apps.

Brightness commands send one brightness-key request through System Events.
Allow Accessibility permission for the host running CuePilot if prompted, as
well as Automation permission. These are relative adjustments, not exact
percentages. Their effect depends on the keyboard/display setup and may not
work with external monitors; the menu reports the request, not a measured change.

If the log says `osascript is not allowed to send keystrokes. (1002)`, open
**System Settings → Privacy & Security → Accessibility** and enable the app
that launched CuePilot (for example, Terminal, iTerm, or your editor when using
its integrated terminal). Add it with **+** if missing. Quit and reopen that
host, then run `uv run cuepilot` again. Under **Privacy & Security → Automation**,
also allow the host to control **System Events** if requested. Recognition and
command routing have already succeeded when this keystroke error appears.

### Manual checks

1. Leave the local Laya server running and start `uv run cuepilot` in a terminal.
2. Wait for **Listening** in the menu. Speak a complete command above, then wait
   for its result.
3. Verify Chrome/Spotify opens, a website opens in a Chrome tab, Spotify's track
   or playback state changes, or brightness changes by one step. Check the menu's
   transcript preview if nothing happens; terminal logs contain detailed errors.
4. Allow any macOS microphone, Automation, or Accessibility prompts for the
   terminal/host running the app. Relaunch CuePilot after changing permissions.
5. Pause from the menu and speak a command: nothing should execute. Resume and
   repeat. Say “do not open Chrome” to verify it is ignored.

Automated checks (no apps, playback, or display settings are changed):

```sh
uv run python -m unittest discover -s tests -v
```

HTTP requests and scripts run on a separate worker. Pausing or changing language
discards queued commands and pending decisions. An AppleScript that has already
started cannot be undone by pausing. Laya requests time out after 30 seconds;
scripts time out after 10 seconds. No arbitrary scripts are generated from speech.

You can also start it with `uv run python -m cuepilot`. The app stays open until
you choose **Quit CuePilot**.

The entry point selects a platform frontend. The `rumps` dependency applies only
on macOS, so future Windows and Linux frontends can use their own UI libraries.
Shared application behavior can move into `packages/` when it is implemented.

## Workspace dependencies

The root application is a workspace member. Libraries under `packages/*` each have
their own `pyproject.toml`; all members share the root `uv.lock` and `.venv`.
See [packages/README.md](packages/README.md) for adding a library.

```sh
uv add <dependency>                    # Add to the root application
uv add --package <member> <dependency> # Add to a workspace member
uv run --package <member> <command>    # Run in a member's environment
uv lock                               # Resolve the entire workspace
uv sync --locked --all-packages        # Install without updating the lockfile
```

Workspace configuration follows the [uv workspace documentation](https://docs.astral.sh/uv/concepts/projects/workspaces/).
