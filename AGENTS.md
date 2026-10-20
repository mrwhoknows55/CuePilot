# Agent instructions

- Keep changes small and focused on the request. Preserve unrelated user changes.
- Use Conventional Commits for Git commits (`type: brief summary`). Keep messages factual and concise; skip filler.
- Work in small steps: get a simple version working, check it, then improve it as needed.
- Prefer small parts with clear jobs and simple interfaces. Keep data flow and failures easy to follow.
- Remove needless duplication, but wait for a real pattern before extracting shared code.
- This is a Python 3.15+ uv workspace. The root project is the CuePilot app in `src/cuepilot/`; new shared libraries belong under `packages/`, each with its own `pyproject.toml`.
- Use uv for dependencies and commands. Keep `uv.lock` in sync when dependencies change. Declare dependencies in the package that uses them, and use workspace sources for dependencies between members.
- Before changing a library, framework, SDK, API, CLI tool, or cloud-service integration, check its current documentation with Context7: resolve the library ID first, then query the relevant topic. Skip this for general programming and business logic.
- Verify behavior affected by the change. For workspace changes, run `uv sync --locked --all-packages`; for code changes, run the relevant tests or command. Report checks you could not run.
- Avoid adding packages, abstractions, or test scaffolding until the code needs them. Choose the simplest solution that handles the current problem.
