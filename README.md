# CuePilot

A macOS menu bar application managed as a Python 3.15+ uv workspace.

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

On macOS, CuePilot appears in the menu bar. Left or right click it for the About
window and Quit item. The terminal shows startup, About, and Quit logs.
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
