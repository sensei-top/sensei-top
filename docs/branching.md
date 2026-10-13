# Branching

The repository follows gitflow. Two branches are permanent, three kinds are
short-lived, and every change reaches a permanent branch through a pull
request.

| Branch | Cut from | Merges into | Holds |
|---|---|---|---|
| `main` | | | The released state. Every commit on it is the merge of a release or a hotfix, tagged `vX.Y.Z`. |
| `develop` | | | Integration: finished work that has not shipped yet. It is GitHub's default branch, so a new pull request targets it without anyone choosing. |
| `feature/<topic>` | `develop` | `develop` | One change: a feature, a fix, a refactor, a document. |
| `release/<X.Y.Z>` | `develop` | `main`, then back into `develop` | A release being stabilized: fixes, documentation and the version number, nothing new. |
| `hotfix/<topic>` | `main` | `main`, then back into `develop` | A fix to what is released that cannot wait for the next release. |

No release has been cut yet and no tag exists. Until the first `release/`
branch merges, `main` stays where it was when `develop` was cut from it.
Nothing waits on it moving: there is no deployment pipeline, because there
is nowhere to deploy to yet.

The release roadmap numbers its plans "release 1" to "release 11", and the
first two ran on branches named `release-1` and `release-2`, which the log's
merge commits still name. In this model those were feature branches. A
plan's branch is `feature/<plan>`; the `release/` prefix is only ever
followed by a version.

## A feature, start to finish

    git switch develop && git pull
    git switch -c feature/<topic>
    # work, commit
    git push -u origin feature/<topic>
    gh pr create --base develop

- **One change per branch**, named for its topic in lowercase with hyphens:
  `feature/mulligan-latency`, not `feature/fixes`.
- **The checks under "Before you finish" in [AGENTS.md](../AGENTS.md) pass
  before the pull request opens**, and so does the privacy scan.
- **Merge with a merge commit, never a squash or a rebase.** A branch's
  commits are the record of how the change was built, and handoff notes cite
  them by hash; a squash leaves every one of those hashes pointing at
  nothing. `git log --first-parent develop` still reads as one line per
  change.
- **Bring `develop` in with a merge, not a rebase**, once the branch has been
  pushed or one of its hashes has been written down anywhere, for the same
  reason.
- **Delete the branch once it is merged**, on origin and locally. Its commits
  stay reachable from `develop`.
- **A branch that needs another unmerged branch's work is cut from that
  branch**, says so in its pull request, and merges after the one it stands
  on.

## Two branches open at once

Before `develop` existed, work ran one branch at a time and nothing here
could collide. Three things in this repository do not merge like ordinary
text.

### Migration numbers

`schema_version` records a migration's number and nothing else, and
`migrate()` applies only the files numbered above the highest one recorded
(`db.py`). Two branches cut from the same `develop` both reach for the same
next number.

Two files with one number in `src/sensei_top/migrations/` are caught:
`discover_migrations()` raises and nothing starts. What is not caught is a
database that already applied one of them. It has the number recorded, so it
skips the other file under that number without a warning, and if the first one
is then renumbered it runs a second time under the new number.

- The number is settled when the branch merges, not when it is cut. If
  `develop` gained a migration in between, renumber to the next free one
  before merging.
- A migration that a real database has applied keeps its number
  ([architecture.md](architecture.md), "Adding a migration": an applied
  migration is never edited). That branch merges first, and the other one
  renumbers.
- Applying one is easy to do by accident. Every CLI subcommand applies the
  pending migrations as it opens the database, `serve` included, so a
  command run from a feature branch against `data/sensei-top.db` applies
  that branch's migrations to it. Use a scratch `--db` unless applying them
  is the point.

### Generated files

`web/src/types/api.ts` and `web/openapi.json` are generated from the API
schema. When two branches both changed the API, the conflict in those two
files is never resolved by hand: merge `develop` in, resolve the Python, run
`pnpm gen:types`, and commit what it writes.

### Lockfiles

The same goes for `uv.lock` and `web/pnpm-lock.yaml`. Take `develop`'s copy,
then run `uv lock` or `pnpm install`, which writes the branch's own
dependency changes back in.

## Where the real install runs

An install that runs from this working tree runs whatever branch is checked
out when `serve` starts, and applies that branch's pending migrations to the
real database ("Migration numbers" above). It runs from `develop`. Switch
back to `develop` before starting the server, and whenever work on a feature
branch stops.

## A release

    git switch develop && git pull
    git switch -c release/<X.Y.Z>

1. On the branch: the version number, the same in all three files that
   carry it (`version` in `pyproject.toml`, `web/package.json` and
   `desktop/package.json`; `uv lock` then refreshes `uv.lock`), fixes
   and documentation. A new feature waits on `develop` for the next release.
   And in `CHANGELOG.md`: rename `## [Unreleased]` to `## [X.Y.Z] - <date>`,
   add a fresh empty `## [Unreleased]` above it, and update the link
   references at the bottom. The release's notes are that section,
   extracted by `scripts/release_notes.py`; without it the release job
   fails on purpose.
2. The checks under "Before you finish" in [AGENTS.md](../AGENTS.md),
   including the run against a real log that follows them there.
3. A pull request into `main`, merged with a merge commit.
4. The tag `vX.Y.Z` on that merge commit, pushed.
5. `main` merged back into `develop`, so that a fix made on the release
   branch is not lost and the tag is reachable from `develop`.
6. The snapshot, run by the maintainer, into a clone of the public
   repository whose own configuration sets the public identity ("The public
   repository" below). Twice:

       uv run python scripts/publish_snapshot.py --tag vX.Y.Z --public <clone>
       uv run python scripts/publish_snapshot.py --tag vX.Y.Z --public <clone> --push

   The first is a dry run: it commits the tag's tree to the clone as one
   commit, tags it, and runs `scripts/privacy_scan.py` on the clone's tree
   and then with `--history`; it pushes nothing. Read that commit, then run
   the second, which scans the same commit again and pushes `main` and the
   tag. A finding stops either run before a push. The script refuses a tag
   that is not on `main`, a clone that is not clean, and a clone without
   its own `user.name` and a `@users.noreply.github.com` `user.email`.
7. The tag push starts the release job (`release` in
   `.github/workflows/desktop.yml`) on the public repository, and only
   there. Watch it finish, then check that the release holds `latest.yml`
   and `latest-linux.yml`: they are what an installed copy's updater reads,
   and a release without them reaches nobody.

## A hotfix

    git switch main && git pull
    git switch -c hotfix/<topic>

The fix arrives with its fixture-backed test (non-negotiable 7) and a patch
version, then follows steps 2 to 7 of a release. If a release branch is open
at the time, the hotfix is merged into it as well.

## Commits

- **The subject is `type(scope): summary`**: `fix(cli): describe the
  configured MTGO directory, not the removed share`. The types in use are
  `feat`, `fix`, `docs`, `chore`, `test`, `refactor` and `perf`. The scope is
  the package or area the change touches (`guide`, `llm`, `web`,
  `current-match`) and is left out when there is no single one. The summary
  is in the imperative, lowercase, with no full stop. Older commits do not
  all follow this; new ones do.
- **A commit message is published text.** `scripts/privacy_scan.py --history`
  reads every commit's author, committer and message as well as every file
  the history ever held. No player name, handle, user ID or local path goes
  in a message: the rule for a tracked file ([AGENTS.md](../AGENTS.md),
  "Privacy") is the rule for the log.
- **An outside contribution is signed off** (`git commit -s`), as
  [CONTRIBUTING.md](../CONTRIBUTING.md) describes.

## Who pushes and who merges

Merging into `develop` and `main` is the maintainer's. An agent working in
this repository commits on its own branch. It pushes, opens a pull request
or changes anything on GitHub only when asked to, and says what it is about
to do before doing it.

The one exception is an unattended run the maintainer starts on purpose
(`.claude/overnight/run.sh`, described in the running-a-plan skill).
Starting it is the word: the driver pushes, opens and merges each pull
request on the maintainer's behalf, only after running the checks and the
privacy scan itself, and leaves a note per merge for the maintainer to read
afterwards. A session the driver starts still never pushes or merges on its
own.

## The public repository

This repository's history is not going to be published
([status.md](status.md), "Waiting on the user"). The public repository
starts as a new repository holding a one-commit snapshot of the tree, and
its `main` and `develop` both start at that commit. It cannot be this
repository with its branches rewritten: GitHub keeps the commits of every
pull request under `refs/pull/*`, where a force-push does not reach them.

Its commits identify the maintainer, by decision: the name git records
today, and GitHub's no-reply address for the maintainer's account in place
of a personal inbox. Both are set in that clone's own configuration
(`git config user.email`, without `--global`), so the working repository
keeps its own. The rule for a tracked file does not change: the identity
goes in the log, never in a file.
