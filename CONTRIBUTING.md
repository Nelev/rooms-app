# Contributing

Work is split into the tasks on the [project board](https://github.com/users/Nelev/projects/1), built in parallel by people and coding agents.

## Parallel-agent rules

- **One task = one branch = one PR.** Branch `task/<ID>-<slug>` (e.g. `task/S-01-repo-scaffold`), one PR per task.
- **Stay in your paths.** Touch only the paths the task lists, plus their tests and the minimal wiring the task needs (a Makefile target, a CI step).
- **Stack, don't wait.** When a task's dependency is not merged yet, branch from the dependency's branch and open the PR against it.
- **Write as little code as possible.** Reuse the CoA repo and earlier tasks, prefer library features to hand-rolled code, and add no speculative abstractions or features beyond the task.
- **Check, don't guess.** When unsure about a library API or a best practice, read the current docs. Next.js 16 differs from most training data: read `frontend/AGENTS.md`.
- **Never push to `main`**, never merge your own PR, never force-push someone else's branch.

## Setup

Needs [uv](https://docs.astral.sh/uv/), Node 24 with [pnpm](https://pnpm.io/), Docker and `make`.

```sh
cp .env.example .env
make dev    # Postgres in Docker, API on :8000 (/health), frontend on :3000
make test   # backend and frontend tests
make lint   # ruff, mypy, Biome, tsc
make e2e    # the Playwright suite (e2e/) on the docker compose stack, replaying the recorded model calls (no key needed)
            # a change to a prompt, a tool, a role's model or the catalog needs `make e2e-record` (a key: it costs money)
```

`docker compose up -d --build` runs the whole stack in containers.

CI runs the backend or frontend workflow when a PR changes that side (any base branch, so stacked PRs are checked too). A PR that touches neither side (root files, docs) runs no checks, so do not make these checks required in branch protection: a required check that never runs leaves the PR pending forever.
