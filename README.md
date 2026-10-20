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
microphone. Left or right click it to see the recent input level and latest
transcript, choose English or the Mac's first preferred system language, pause or
resume capture, open About, or quit. English is selected by default. The terminal
logs the input device, sample rate, and recognized speech. CuePilot groups speech
using input level and a short silence gap, then transcribes it locally with MLX
Whisper. The first launch downloads the `mlx-community/whisper-tiny` model; later
launches use the local cache. Transcripts are only displayed and logged for now.
If the model does not support the system language, its menu option is disabled.

macOS may ask for microphone access. If the menu reports **No input signal**,
check **System Settings → Privacy & Security → Microphone** for the terminal
running CuePilot, then check the selected device under **Sound → Input**.
CuePilot keeps live audio and transcripts in memory. It does not save recordings
or send microphone audio to a service. The capture code emits 20 ms mono PCM
chunks; a dedicated worker groups them before transcription.

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
