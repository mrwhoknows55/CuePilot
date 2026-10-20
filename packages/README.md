# Workspace libraries

Add shared Python libraries here when they need their own dependencies or package boundary.
Each directory matched by `packages/*` must contain its own `pyproject.toml`.

Create a library from the repository root:

```sh
uv init --lib packages/cuepilot-core
uv add cuepilot-core --workspace
```

The second command adds the library to the root application's dependencies and configures
its source as `{ workspace = true }`, so uv installs the local member in editable mode.
