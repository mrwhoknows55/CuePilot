# CuePilot

A Python 3.15+ application managed as a uv workspace.

```text
.
├── pyproject.toml          # Root application and workspace configuration
├── uv.lock                 # Shared dependency lockfile
├── src/cuepilot/           # Application package
└── packages/               # Future workspace libraries
```

## Development

From the repository root:

```sh
uv sync --all-packages
uv run cuepilot
```

You can also run the application with `uv run python -m cuepilot`.

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
