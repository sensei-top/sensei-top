# Contributing to Sensei Top

Thank you for considering it. This project has one maintainer, so the most
useful thing a contribution can be is easy to check.

## What helps most

1. **A log-format fix with a fixture.** Arena and MTGO change their logs
   without notice, and a captured log is the only early warning this
   project has. A fix that arrives with the log lines that broke it,
   anonymized, is worth more than any feature.
2. **A bug report with the numbers.** What the dashboard showed, what the
   game showed, and which match it was.
3. **Documentation that was wrong or missing** when you needed it.

The issue forms on GitHub ask for exactly this: "A log change" for a
log-format report, "A bug" for the rest, "A feature" for a request.

A new feature is welcome too, but open an issue before writing it. Several
things that look like gaps are decisions ([docs/status.md](docs/status.md),
"Limited on purpose"), and it is cheaper to find that out first.

## Before you write code

Read [AGENTS.md](AGENTS.md). It is the rulebook for anyone changing this
repository, human or agent, and its non-negotiables are exactly that. The
ones that surprise people most:

- Raw log events are stored verbatim and never rewritten.
- Missing data is `NULL` and a warning, never a guess.
- Every parsing rule has a test against a real captured log, and the
  expected values come from reading the log, not from running the code.
- Nothing calls a paid API unless the user configured a key and pressed a
  button.

## Where to branch

Cut your branch from `develop`, name it `feature/<topic>`, and open the pull
request against `develop`. `main` holds releases only. The whole model, and
what to do when your branch and another one collide, is in
[docs/branching.md](docs/branching.md).

The public repository starts from a single commit. The history before the
first public release was written against the maintainer's own match data,
and old versions of a few files held local paths and a player handle, so
that history was squashed rather than published. Everything since is in
the open.

## Working on the code

    uv sync
    cd web && pnpm install
    pnpm dev            # Vite on :5173, proxies /api to :8000 (run `uv run sensei-top serve` too)
    pnpm test           # vitest
    pnpm gen:types      # regenerate src/types/api.ts after changing the API

The dashboard's types are generated from the API's OpenAPI schema and
committed, so the build fails on a renamed field instead of rendering
`undefined`. Tests run against anonymized real logs in `tests/fixtures/`.
[What Arena's log actually does](docs/arena-log.md) is worth reading before
touching the parser.

## Before you open a pull request

    uv run ruff check .
    uv run pytest -q
    cd web && pnpm lint && pnpm build

All four must pass. If one fails and you believe the check is wrong, say so
in the pull request instead of changing the check.

If a player would notice the change, add a line under `Unreleased` in
`CHANGELOG.md`; the release notes are built from it.

## Fixtures and privacy

A fixture is a real log, and a real log names real people. Before a
captured log goes into a commit:

- replace player names, user IDs and local paths with placeholders;
- run `uv run python scripts/privacy_scan.py`, which reports categories,
  paths and counts and never prints an identifier.

Never attach your database, your `Player.log` or your config file to an
issue. The config file can hold an API key.

## Sign your commits off

Every commit in a pull request carries a `Signed-off-by` line:

    git commit -s

That line is your statement of the Developer Certificate of Origin
([DCO](DCO)): you wrote the change, or you have the right to submit it
under this project's licence. There is no contributor licence agreement to
sign, and you keep your copyright.

## The licence of your contribution

Sensei Top is licensed AGPL-3.0-only ([LICENSE](LICENSE)). A contribution is
licensed under that same licence, by you, when you submit it. Nothing more
is asked, which also means the project cannot put your work under any
other licence without your agreement.

## Conduct

The [Code of Conduct](CODE_OF_CONDUCT.md) applies in every project space.
