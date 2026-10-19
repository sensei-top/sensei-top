# The opt-in Claude API call

Read this when touching `llm/`, a `.../narrative` POST route, or
`GenerateCard`, or when planning anything hosted. It explains the one
exception AGENTS.md non-negotiable #5 carves out, exactly what does and does
not cross the loopback boundary because of it, why no hosted service of
this project writes on a user's behalf today, and what the planned paid
report allowance would change.

AGENTS.md states rule 5 as four short lines. This document is where the
reasoning behind them lives — read it before arguing with any of them.

## Why this is a product decision, not a preference

A local analytics tool that bills its user without a clear, reversible choice
on their part is a **different product** from the one this is. That is the
whole of the argument, and it is why rule 5 is a non-negotiable rather than a
default someone may tune.

Before this feature existed, "this app cannot spend money" was a *structural*
fact — there was no HTTP client for Anthropic in the runtime dependency set at
all. It is now a *configuration* fact: no key, no call. That is a genuinely
weaker guarantee, and the three things that keep it honest are `llm/config.py`
returning `None`, every caller checking for it, and the tests named at the
bottom of this section.

**There is no background worker, and that is load-bearing.** One used to exist
— it polled for a live opponent and called out automatically. It was deleted
in migration 019 and stays deleted. A scheduled or event-triggered call is a
different feature with a different consent story, not a variant of this one;
building it means revisiting rule 5, not extending it.

**The one exception, stated plainly:** the five narrative routes send match
evidence to Anthropic's API when — and only when — the user has configured a
credential. That is the deliberate trade rule 5 makes. It does not extend to
anything else this app fetches or sends.

With no credential configured, none of the five routes may even build a
client: `tests/test_llm.py::test_no_credential_means_no_client_is_constructed`
pins it for the match report, the leak finder, the deck guide and the RCQ
guide, and
`tests/test_coach_api.py::test_no_credential_means_no_client_is_constructed`
for the coach.

## The standard for the free downloads

The card database, card images, archetype definitions, the MTGO/Melee
tournament corpus, and the TopDeck.gg tournament source
(`metagame/topdeck.py`, `metagame/config.py`) are **not** governed by the
metered-call rule. Their standard:

- **Reference lookups only.** They name a card or a date, not a game.
- **Fail-soft, always.** An offline machine uses what it cached and says how
  old that is. Startup never blocks or fails on the network. A failed fetch
  degrades to an inline message — never a broken page, never a 500.
- **No more than the feature needs**, with the docstring saying what is
  fetched and why.

**TopDeck.gg is the one wrinkle**: unlike the other free downloads it requires
a user-supplied credential. It is still not a metered call — the key exists for
rate-limiting and attribution, never billing — so it is configured the same way
(`sensei-top config --set-topdeck-key`, or a `TOPDECK_API_KEY` env var,
resolved by `metagame/config.py`, a *sibling* to `llm/config.py` rather than an
extension of it) while staying governed by the free-download standard above.
With no key configured the corpus refresh simply skips that source, no
different from any other unreachable download. See `docs/metagame.md`.

## What changed, and what didn't

Every written artifact in this project used to be produced by hand: the app
built a prompt, the dashboard offered it as copyable text
(`CopyPromptCard`), and the user pasted it into a Claude chat, saved the
answer, and ran a CLI import. That round trip — `docs/brief.md` and
`docs/guide.md` describe it in full — is how the first deck guide was
written, and it still works exactly as before. The import is optional now:
each card takes the pasted answer in a box and saves it itself ("Saving a
pasted answer", below).

What's new is a second path, opt-in: configure a Claude credential, and the
same five "get a written narrative" surfaces become one-click "write it with
Claude" buttons that call the API server-side and store the answer. No
credential, no difference from before — every generate route returns 503 and
the frontend falls back to `CopyPromptCard`.

**Decided 2026-10-07: both paths stay, and both are the user's own.** The
2026-10-01 decision (writing Pro-only through a hosted proxy, the copy
prompt removed, three tiers, an account) is reversed. **Amended
2026-10-12:** a paid subscription is planned, not built, and its monthly
allowance of reports would be a third path, written by a hosted proxy
holding the maintainer's key ("Nothing hosted writes for the user",
below). It adds that path and removes neither of these: both stay free,
and neither ever needs an account. What follows from that:

- `CopyPromptCard` and the "Show the prompt" toggle stay, and the prompts
  keep improving as features of their own. A user with no key, or with an
  assistant subscription they already pay for, generates by pasting the
  prompt into it and the answer back into the card.
- A configured credential is a user path, not a development setting. The
  dashboard's Settings say so plainly, and the website never uses the
  phrase "AI" as the pitch: the tracker, the field and the current-match
  reads are the product, and writing is an option on top.
- **Planned, not built: a provider adapter** (`ROADMAP.md`). The credential
  becomes a provider plus a base URL, a key and a model id, so the same
  five routes can call Anthropic, any OpenAI-compatible endpoint, or a
  local model (Ollama, LM Studio) on the machine. Three consequences are
  decided with it: "the only module that imports `anthropic`" becomes "the
  only package that talks to a model" (`llm/`), with one adapter per
  protocol; every stored narrative carries the model id that wrote it, and
  the dashboard shows it, because a report from a small local model is
  not the report the prompt was tuned for; and the coach's web search,
  an Anthropic server tool, degrades to the reading list alone on any
  provider without it, said on the Coach page before the press. Cost
  stays measured from the response's usage and prices `NULL` for a model
  the table does not know (rule 4), which is every local model.
- The brief, coverage and sideboard-plan cards stay on the copy prompt
  until the adapter work gives them a generate route of their own, which
  extends rule 5's five-route list and the write set
  `test_only_authored_artifact_routes_write` pins.

This document describes the code as it stands. The adapter is listed in
`docs/status.md`, "Features not built".

The structural-fact-to-configuration-fact trade this makes is stated above,
along with what pins it down.

## Credential resolution

`src/sensei_top/llm/config.py` is the only place a *metered, billing*
credential is read — the Claude API key. The free, rate-limited TopDeck.gg
credential is resolved by its own sibling module, `metagame/config.py`, under
the free-download standard above rather than this rule.

Order, first match wins:

1. `ANTHROPIC_API_KEY` environment variable.
2. The system keyring (Windows Credential Manager, Secret Service on Linux),
   service `sensei-top`, username `claude`, read through `secrets.py`. That
   module is a generic, fail-soft store and imports nothing from `llm/`; this
   module stays the only place the credential is *resolved*. The `fail` and
   `null` keyring backends count as "no backend" (silently skipped); a backend
   that exists but errors logs a WARNING (never the value) and resolution
   moves on to the file.
3. `~/.config/sensei-top/config.toml` (`$XDG_CONFIG_HOME` if set), or on
   Windows `%APPDATA%\sensei-top\config.toml` (`llm/config.py::config_path`),
   a `[claude]` table:
   ```toml
   [claude]
   api_key = "sk-ant-..."
   model = "claude-opus-5-5"
   effort = "high"
   ```
   Written by `sensei-top config --set-model/--set-effort`, and by
   `--set-key` only when there is no keyring (below), `chmod 600`. Model and
   effort always come from this table, whichever source supplied the key; a
   key already here keeps working, and nothing moves it unless asked. Never
   tracked, never logged, never echoed back by `config --show` beyond its
   last 4 characters.

### Writing a key

    printf '%s\n' "$KEY" | sensei-top config --set-key -
    sensei-top config --set-key -           # on a terminal: prompts, no echo

`-` reads the key from stdin, so it never sits on a command line where
`ps` or the shell's history can see it; that is the form the desktop shell
uses. `--set-key KEY` still works, for scripts that already pass it that
way. `--set-topdeck-key` takes `-` the same way. An empty key is refused
rather than read as "remove it"; removing is `--clear-key` (or
`--clear-topdeck-key`), which deletes the key from the keyring and from the
file both.

Where it goes: the system keyring when there is a usable one, and then the
file's copy, if any, is removed so the two cannot disagree. With no keyring
(the `fail`/`null` backends, or one that refuses the write) it goes to the
file, and the command says why. `config --move-keys-to-keyring` moves keys
already in the file into the keyring, on request only: no other command
moves one. If the keyring already holds a different key it changes nothing
and exits non-zero, since either choice would change which key is in force.

`config --json` prints every setting as one JSON object for the desktop
shell: the `[arena]`, `[mtgo]` and backup values, the model and effort, the
models offered, and for each key only `key_set` and `key_source` (`env`,
`keyring`, `file` or `null`), never the key. `key_source` comes from
`llm/config.py::key_source()` and `metagame/config.py::key_source()`, the
same resolution `load()` runs; `cli.py` writes through `secrets.py` but never
decides which key is in force.

The coach reads the same `[claude]` table plus an optional `[claude.coach]`
table layered on top of it, resolved by `llm/config.py::load_coach()`:

```toml
[claude.coach]
model = "claude-fable-5-1"
effort = "high"
web_search = true
```

Any key left out of `[claude.coach]` falls back to `[claude]`'s own value
(or the built-in default), and `load_coach()` returns `None` under the exact
same missing-credential rule as `load()` — the coach is not a separate
credential, only an optional override of model, effort, and whether it may
search at all. Written by `sensei-top config --set-coach-model`,
`--set-coach-effort`, and `--coach-web-search on|off`; `config --show` prints
the resolved coach override alongside the base model/effort when one is set.

The TopDeck.gg key follows the same order (`TOPDECK_API_KEY`, keyring username
`topdeck`, `[topdeck]` in the file) in `metagame/config.py`.

Missing or malformed input at either layer resolves to "not configured"
(`load()` returns `None`) plus a `log.warning` — never an exception. This is
the same fail-soft posture `metagame/source.py` and `card_images.py` already
use for the free downloads: an unreachable or misconfigured feature degrades
the one surface that needs it, not the whole app.

## What calls out, and what it sends

Only `src/sensei_top/llm/client.py` imports `anthropic`, and only these
five routes ever construct a client — each fired by a button press, never a
schedule, never a background worker:

| Route | Sends | Writes |
|---|---|---|
| `POST /api/matches/{id}/report/narrative` | `review/narrative.py`'s existing `full_prompt` — this game's turn-by-turn shape and the report's findings, no raw hand or graveyard | `match_narrative` |
| `POST /api/guide/{key}/narrative` | `guide/narrative.py`'s existing `full_prompt` — the player's 75 and the field's top archetypes' consensus staples, both with oracle text | `deck_narrative` **and** `matchup_brief` (every matchup plan the guide covers) |
| `POST /api/review/leaks/narrative` | `review/leaks_narrative.py`'s existing `full_prompt` — one bullet per recurring pattern with its win-rate interval | `leaks_narrative` |
| `POST /api/coach/narrative` | `coach/narrative.py`'s `full_prompt` — cross-deck win rates and recurring patterns over every completed constructed match, worked example losses, a curated reading list, and the previous report's own progress metrics; every field is a rate, a pattern label, or a reading id — no opponent name, user id, local path, or deck GUID, with the one documented exception of an example game's own `match_id` (`docs/coach.md`). Also takes an optional JSON body, `{"model": "..."}`, from the Coach page's model dropdown — one of `llm/client.py::REPORT_MODELS`, else a 422 naming the allowed ids; left out, the call uses the configured coach model exactly as before the dropdown existed. | `coach_report` (a new row every time — a coach report is history, never overwritten) |
| `POST /api/guide/{key}/rcq/narrative` | `guide/rcq.py`'s `rcq_prompt` — the exact 75 the user pasted, with oracle text, the list's diff against the field's consensus, the expected archetypes the user picked (corpus keys, each with consensus and oracle text), the field's shares since the format reset and over the last 14 days, and every event of the last 7 days (date, name, tier, players, top-8 archetypes). The body is `{decklist, expected[], own?}`; no opponent name, handle or local path. 503 with no credential, 502 on an `LLMError` | `rcq_guide` (a new row every time — each is the record of one event's preparation) |

All five routes sit behind `api/guard.py`, which refuses a POST from a
foreign `Origin` or without the dashboard's `X-Tracker-Client` header before
it reaches the route, so another page open in your browser cannot trigger a
metered call.

### Saving a pasted answer

Seven `PUT` routes store an answer the user pasted into a card, one per
card that offers a prompt: `PUT /api/matches/{match_id}/report/narrative`,
`PUT /api/review/leaks/narrative`, `PUT /api/coach/narrative`
(`?format=`), `PUT /api/guide/{key}/narrative`,
`PUT /api/guide/{key}/briefs/{archetype_key}`,
`PUT /api/guide/{key}/coverage` and `PUT /api/guide/{key}/rcq/narrative`.
None constructs a client or sends anything anywhere. Each reads the
answer through `answers.py::read_answer`, the parser the CLI importers
use, and writes the table its generate route or importer writes
(non-negotiable #6's allowlist; `test_only_authored_artifact_routes_write`
pins all seven). The answer's `for` line must name this card: an answer
for another card, or with no `for` line at all (which the CLI still
accepts, with a warning), is refused with a sentence saying why (422)
and nothing is stored. An answer over 256 KB is refused before anything
is looked up (413). A pasted answer is stored with the author `pasted`
and no cost or token counts, which stay `NULL` ("Model, effort, and
cost", below); the dashboard says "Pasted in." where it would name a
model. The stored prompt is the copied prompt rebuilt at save time,
except on the brief and coverage routes, which store what
`brief --import` stores, the build context (`docs/brief.md`).

The coach's call is also the only one that can reach the network *during* the
call, not just at its start and end: `write_report` (below) hands Claude a
server-side web-search tool restricted to `coach/canon.py::ALLOWED_DOMAINS`,
a fixed list of magic-strategy and metagame sites. The model decides whether
to search at all — most of the prompt needs no search — and never sees a
raw URL outside that list to visit.

Each call also logs at `INFO` level — the model and effort before the call,
then input/output tokens, cost, and elapsed time once it completes (or a
`WARNING` if it fails). `llm/client.py` sets its own logger's level
explicitly, and `logs.py` lets the `INFO` lines of any `sensei_top.llm`
logger through to both the console and the log file at the default levels,
so a user watching `serve` sees what a button press spent (rule 5, "never
silent"). Every other logger's `INFO` stays out.

Under `--verbose` the log file also takes the `anthropic` SDK's own `DEBUG`
lines, and its "Request options" line holds the request body: a generate
call's whole prompt, which is the user's own match data, written to
`<db dir>/logs/sensei-top.log`. The credential is not in it. Without
`--verbose` the file takes neither.

**A generate call sends the copied prompt without its last section.**
The prompt a card offers to copy ends with the answer contract
(`answers.py::answer_format`): a `for` line naming the card, a
`context` hash of what the prompt was built from, and the JSON shape to
answer in, one `{"prose": ...}` object for the prose cards. A generate
call sends the prompt without that contract (`full_prompt`, the coach's
`CoachPrompt.prompt`), because its reply is stored whole or read through
the tool's own schema. The evidence is the same text either way, tested
the same way, one route's builder at a time:
`test_narrative_prompt_carries_no_local_paths` (`tests/test_api.py`,
`tests/test_narrative.py`) for the match report,
`test_leaks_context_carries_no_local_paths` for the leak finder,
`test_build_guide_context_carries_no_local_paths` for the deck guide, and
`test_build_coach_prompt_over_a_projected_database_no_privacy_leak` with
`tests/test_coach_evidence.py`'s two `test_privacy_*` tests for the coach.
The RCQ guide's prompt has no such test. These tests are load-bearing
now in a way they were only decorative before: a bug in one of those
builders used to produce a prompt a human read before pasting anywhere; now it's a
prompt the API sends.

The matchup brief (`GET /api/current-match/brief`) deliberately has **no**
generate button — it stays `CopyPromptCard`-only. It still gets filled
automatically for any archetype the deck guide covers, because generating the
guide writes into `matchup_brief` the same way `guide --import` already does
via `brief/from_guide.py`.

## Model, effort, and cost

Default `claude-opus-5-5`, `thinking: {"type": "adaptive"}`,
`output_config: {"effort": "high"}` — both overridable per-user via
`sensei-top config --set-model` / `--set-effort`. The deck guide additionally
requests structured output (`output_config.format`) against the existing
`_GUIDE_TOOL["input_schema"]` schema, so the generate path returns the exact
JSON shape `guide_narrative_from_json` already parses — one validation path,
not two.

Every generated artifact records `model`, `input_tokens`, `output_tokens`, and
`cost_usd` computed from the response's own `usage` block against a small
priced-models table in `llm/client.py` (`_PRICES`): `claude-opus-5` ($5/$25
per MTok in/out), `claude-opus-5-5` ($4/$20), `claude-fable-5-1` ($10/$50),
`claude-sonnet-5` ($2/$10), and `claude-haiku-4-5` ($1/$5) — five priced
models, a `--set-model`/`--set-coach-model` override may name any of them.
The coach's own dropdown offers only four of the five (`REPORT_MODELS`,
above) — every priced model but Haiku 4.5, which rejects the adaptive
thinking and explicit effort `write_report` always sends. An unrecognized
model prices at `NULL`, never a guess, per non-negotiable #4. An
imported or pasted narrative has no cost at all — those columns stay
`NULL`, not `0.0`, because zero would claim a fact ("this cost nothing")
rather than record an absence ("this wasn't priced").

The coach's cost adds one more term: each web search the model actually runs
costs $10 per 1,000 searches (`_SEARCH_COST_PER_1000`, confirmed against
Anthropic's live pricing 2026-09-18) — $0.01 a search — on top of its
token cost, accumulated across every response in the call including any
`pause_turn` continuation. The other four routes never search, so this term
is always zero for them.

**Prompt caching: the coach's loop only.** Every request in
`write_report`'s loop sends top-level automatic caching (`cache_control:
{"type": "ephemeral"}`, the five-minute lifetime). The API caches the
prompt up to its last block, and the next request in the loop, whether a
server-side search iteration or a `pause_turn` continuation re-sending the
conversation so far, reads that prefix back instead of paying the full input
price for it again. No other route is marked. Each of them sends one request
and samples once, so nothing would ever read what it wrote, and a
five-minute cache write costs 1.25× the input price: marking them would
raise their cost. A prefix shared across users would need a hosted proxy,
and none is built ("Nothing hosted writes for the user", below).

A cached call reports its prompt in three counts, and `coach_report` stores
all three (migration 063): `input_tokens` is only the uncached remainder,
`cache_creation_input_tokens` is what the loop wrote to the cache and
`cache_read_input_tokens` what it read back, each summed across the loop.
The prompt's size is their sum. `cost_usd` prices each at its own `_PRICES`
column: a write at 1.25× input, a read at 0.1× (0.05× on Opus 5.5, 0.025× on
Fable 5.1), confirmed against Anthropic's live pricing 2026-10-07. A coach
report written before 063 has `NULL` in both cache columns: not measured,
not zero. Every other route's table keeps `input_tokens` as the whole
prompt, since nothing those routes send is cached.

The Batch API halves both the input and the output price, but answers
asynchronously, in up to a day. A report that arrives while the user waits
on the page is the product, so no route uses it.

Measured per-call costs, from real runs at `effort: high` against the
fixture-backed scratch database used in `tests/test_llm.py`:

| Feature | Measured cost | Notes |
|---|---|---|
| Match report (the `"Coach's summary"` card) | $0.098 | A real 2-game match. The card predates the Coach tab and is unrelated to it — one match, not a cross-deck report |
| Deck guide | $0.066 | Against the fixture's 2-match deck with **no card oracle text loaded** (`sensei-top cards --scryfall` never run on this scratch DB) — a real deck's guide, with oracle text for its own 75 and the field's top archetypes, will cost more; re-measure against a real `$MTGA_LOG` before trusting this number for planning |
| Leak narrative | not yet measured | the fixture has only 2 matches — `leaks.MIN_SAMPLE` (10) can never clear on either side of any comparison, so there was nothing to generate a training plan from |
| Coach report | $0.8482 | Before prompt caching. Opus 5 over a real 245-match database, 2026-09-20: 110,718 input / 9,384 output tokens and 6 web searches (6 × $0.01 = $0.06 of that total). Measured against `$MTGA_LOG`, not the fixture, which can't reach `MIN_SAMPLE` (10) constructed matches. **The prompt is only ~10k tokens**; the billed input is it re-sent on every `pause_turn` continuation, so searches drive this cost, not history size — `--coach-web-search off` takes it to a few cents. See `docs/coach.md` |
| Coach report, Fable 5.1 | $3.2292 | Before prompt caching. Picked from the Coach tab's model dropdown, 2026-09-22, over 249 matches at `effort: high`: 238,886 input / 15,206 output tokens and 8 web searches ($0.08). About 3.8× the Opus 5 run: 2× from the per-token price, the rest from 2.2× the billed input through the same `pause_turn` re-sends. Not a controlled comparison — it was the second report, so its prompt also carried the first. See `docs/coach.md` |
| Coach report, Opus 5.5, cached | $0.5998 | With prompt caching, 2026-10-07, Standard over 360 Standard matches (633 Constructed): 20 uncached input, 42,645 cache-write and 256,003 cache-read tokens (a 298,668-token prompt across the loop), 12,763 output tokens and 8 web searches ($0.08). Uncached, the same counts would have cost about $1.53. The last uncached Opus 5.5 report, 2026-10-02, with the same 8 searches, cost $1.7522 (345,874 input / 14,437 output). Not a controlled comparison: that one predates the per-format report, so its prompt differs |

The first two coach rows predate prompt caching. Only Opus 5.5 was
re-measured with caching on. The other dropdown models have no cached
measurement, so the Opus 5 and Fable 5.1 rows overstate what they cost now.

## The fallback

`GET /api/llm/status` reports `{configured: bool, model: str | None}`,
never the key itself. Each of the five callers reads it and hands
`GenerateCard` (`web/src/components/GenerateCard.tsx`) a `writer`, who
writes the report, from `writerFrom` (`web/src/lib/writer.ts`). The
card builds one body, the same whoever writes: a written note
(`writtenNote`, `lib/written.ts`: who wrote it, when, what it cost and,
when the evidence has moved on since, a sentence saying so), then the
stored prose, or "Nothing written yet." with neither. With no key
configured nobody writes, and that body becomes `CopyPromptCard`'s
children, above its "Copy the prompt" button. With one, the key writes,
and the same body sits above a "Write it with Claude" button ("Rewrite
with Claude" once something is stored) and a "Show the prompt" toggle.
While it writes, the button counts the seconds: these calls are slow,
and a guide at `effort: high` can take minutes.

`Writer` has those two cases, nobody and a key (`docs/frontend.md`,
"Writing prose"). A paid plan's writer, which only a desktop shell would
know of, would be a third; it is not built. Nothing here would change
with it: with no credential configured, the `POST .../narrative`
routes still answer 503, and a plan's press would have to go through the
desktop shell, never through this API.

## Nothing hosted writes for the user

This repository is free software, AGPL-3.0-only (`LICENSE`), with
contributions under the DCO (`CONTRIBUTING.md`): a contributor keeps their
copyright and certifies the right to submit under that licence, so the
maintainer can relicense only what the maintainer wrote. That is accepted,
not overlooked. The licence was AGPL from 2026-09-27, proprietary "for now"
from 2026-10-01, and AGPL again from 2026-10-07; no copy was published in
between, so no user ever held the proprietary notice.

No hosted proxy is built, and today every generate press uses the user's
own credential, on the user's own machine. One is planned since
2026-10-12 (AGENTS.md rule 5): the paid subscription's monthly allowance
of reports, written through a server of ours that holds the maintainer's
key. The 2026-10-01 plan had the same server and three costs: a second
recipient of match evidence, an account, and a secret prompt. The planned
one accepts the first two and refuses the third. The prompt stays
readable in the dashboard and in this repository, the copy prompt and
the user's own credential stay free beside it, and the account is the
subscriber's alone. What is sold is reports inside a subscription, never
tokens, credits or a prepaid balance: Anthropic's terms permit a product
built on the API, not resold access to it. Someone who runs a modified
copy as a service for others owes its users the source under AGPL
section 13, which is the licence working as intended, not a case this
project has to design for.

The `writer` under "The fallback" above is where the allowance would
enter the dashboard, as a third case beside nobody and a key; it is not
built.

Apart from that planned proxy and the account service behind it, which
holds an email, a sign-in identity and an entitlement and never a match,
what this project may host is static and receives nothing: a version
file the app checks once a day (disclosed in the README, switchable in
Settings; the request carries the version asked for and nothing else) and,
only with Daybreak's written consent, a snapshot of the field feed
(`docs/metagame.md`). Neither is a call out in rule 5's sense, and neither
ever sees a match. A diagnostics bundle exists only as a file the user
makes and sends by hand, redacted before it is written.

The planned allowance receives match data, so these are the statements it
makes false, and building it starts with rewriting them: the exception at
the top of this document, which names
the user's configured provider alone; rule 5's opening in AGENTS.md; "no
account, no upload" in AGENTS.md's paragraph about the project, which the
README and the dashboard's footer repeat; the fourth promise in
`SECURITY.md`, that no match data leaves the machine except the prompt of
a report the user asked for, and its third, that nothing calls a paid API
without a configured key; the item about collecting or sharing matches
under "Never" in `ROADMAP.md`; the first item of the "What never leaves
your machine" card and the item about collecting or sharing matches in the
"What is not planned" card, on
the site's home page in both languages (`site/index.html`,
`site/pt-br/index.html`); and the claim under "What calls out, and what
it sends" that per-route tests cover what leaves the machine. Each stays
true of the free app, so the rewrite adds the subscriber's case beside it
rather than removing it.
