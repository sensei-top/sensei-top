# The opt-in Claude API call

Read this when touching `llm/`, a `.../narrative` POST route, or
`GenerateCard`, or when planning anything hosted. It explains the one
exception AGENTS.md non-negotiable #5 carves out, exactly what does and does
not cross the loopback boundary because of it, and the boundary a hosted
proxy stays behind.

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
returning `None`, every caller checking for it, and the test named at the
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
written, and it still works exactly as before.

What's new is a second path, opt-in: configure a Claude credential, and the
same five "get a written narrative" surfaces become one-click "write it with
Claude" buttons that call the API server-side and store the answer. No
credential, no difference from before — every generate route returns 503 and
the frontend falls back to `CopyPromptCard`.

**Decided 2026-10-01, not built yet: the copy-prompt path goes, and writing
becomes Pro-only.**
- The hosted proxy (plan 8) becomes the only way a user generates. A local
  credential resolved here becomes a development setting.
- `CopyPromptCard` and the "Show the prompt" toggle are removed. An
  unconfigured surface shows the Pro call to action.
- There is no trial. Three tiers: free, with no writing; a free account,
  with one coach report and two deck guides a month; Pro, with five and ten.
  Every generation goes through the same proxy, as a button press with
  measured cost. The account is for the hosted service only; nothing that
  shows Wizards IP needs one. The numbers are reviewed against measured cost
  in plan 8.
- The brief surfaces get CTA routes of their own (`AGENTS.md`, rule 5).
- `guide --import` and `brief --import` stay as CLI tools for development and
  tests.
- With no prompt view left, what the proxy receives has to be stated
  wherever plan 8 designs it, in the privacy notice included.

This section describes the code as it stands until then. The work is listed
in `docs/status.md`, "Features not built".

The structural-fact-to-configuration-fact trade this makes is stated above,
along with what pins it down.

## Credential resolution

`src/sensei_top/llm/config.py` is the only place a *metered, billing*
credential is read — the Claude API key. The free, rate-limited TopDeck.gg
credential is resolved by its own sibling module, `metagame/config.py`, under
the free-download standard above rather than this rule.

Order, first match wins:

1. `ANTHROPIC_API_KEY` environment variable.
2. `~/.config/sensei-top/config.toml` (`$XDG_CONFIG_HOME` if set), or on
   Windows `%APPDATA%\sensei-top\config.toml` (`llm/config.py::config_path`),
   a `[claude]` table:
   ```toml
   [claude]
   api_key = "sk-ant-..."
   model = "claude-opus-5"
   effort = "high"
   ```
   Written by `sensei-top config --set-key/--set-model/--set-effort`,
   `chmod 600`. Never tracked, never logged, never echoed back by
   `config --show` beyond its last 4 characters.

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

The coach's call is also the only one that can reach the network *during* the
call, not just at its start and end: `write_report` (below) hands Claude a
server-side web-search tool restricted to `coach/canon.py::ALLOWED_DOMAINS`,
a fixed list of magic-strategy and metagame sites. The model decides whether
to search at all — most of the prompt needs no search — and never sees a
raw URL outside that list to visit.

Each call also logs at `INFO` level — the model and effort before the call,
then input/output tokens, cost, and elapsed time once it completes (or a
`WARNING` if it fails). `llm/client.py` sets its own logger's level
explicitly, so these lines used to reach the console whether or not
`--verbose` was given. Since the log file (`logs.py`), each handler filters
on its own level: the console takes `ERROR`, `WARNING` with `--verbose`, and
the file `WARNING`, `DEBUG` with `--verbose`. So the `INFO` lines now reach
the log file under `--verbose` and the console never; only the `WARNING`
reaches either without it. That is a regression, recorded in
`docs/status.md`; the cost itself is still stored with each narrative.

Under `--verbose` the log file also takes the `anthropic` SDK's own `DEBUG`
lines, and its "Request options" line holds the request body: a generate
call's whole prompt, which is the user's own match data, written to
`<db dir>/logs/sensei-top.log`. The credential is not in it. Without
`--verbose` the file takes neither.

**No prompt text changes because of this feature.** These are the same
`full_prompt` builders the copy-paste path has always used, tested the same
way — `test_narrative_prompt_carries_no_local_paths` and
`test_context_never_carries_any_game_in_progress_signal` cover exactly what
leaves the machine, and they are load-bearing now in a way they were only
decorative before: a bug in one of those builders used to produce a prompt a
human read before pasting anywhere; now it's a prompt the API sends.

The matchup brief (`POST /api/current-match/brief`) deliberately has **no**
generate button — it stays `CopyPromptCard`-only. It still gets filled
automatically for any archetype the deck guide covers, because generating the
guide writes into `matchup_brief` the same way `guide --import` already does
via `brief/from_guide.py`.

## Model, effort, and cost

Default `claude-opus-5`, `thinking: {"type": "adaptive"}`,
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
model prices at `NULL`, never a guess, per non-negotiable #4. A
hand-imported (copy/paste) narrative has no cost at all — those columns stay
`NULL`, not `0.0`, because zero would claim a fact ("this cost nothing")
rather than record an absence ("this wasn't priced").

The coach's cost adds one more term: each web search the model actually runs
costs $10 per 1,000 searches (`_SEARCH_COST_PER_1000`, confirmed against
Anthropic's live pricing 2026-09-18) — $0.01 a search — on top of its
token cost, accumulated across every response in the call including any
`pause_turn` continuation. The other three routes never search, so this term
is always zero for them.

Measured per-call costs, from real runs at `effort: high` against the
fixture-backed scratch database used in `tests/test_llm.py`:

| Feature | Measured cost | Notes |
|---|---|---|
| Match report (the `"Coach's summary"` card) | $0.098 | 500 input / 200 output tokens, a real 2-game match. The card predates the Coach tab and is unrelated to it — one match, not a cross-deck report |
| Deck guide | $0.066 | Against the fixture's 2-match deck with **no card oracle text loaded** (`sensei-top cards --scryfall` never run on this scratch DB) — a real deck's guide, with oracle text for its own 75 and the field's top archetypes, will cost more; re-measure against a real `$MTGA_LOG` before trusting this number for planning |
| Leak narrative | not yet measured | the fixture has only 2 matches — `leaks.MIN_SAMPLE` (10) can never clear on either side of any comparison, so there was nothing to generate a training plan from |
| Coach report | $0.8482 | Opus 5 over a real 245-match database, 2026-09-20: 110,718 input / 9,384 output tokens and 6 web searches (6 × $0.01 = $0.06 of that total). Measured against `$MTGA_LOG`, not the fixture, which can't reach `MIN_SAMPLE` (10) constructed matches. **The prompt is only ~10k tokens**; the billed input is it re-sent on every `pause_turn` continuation, so searches drive this cost, not history size — `--coach-web-search off` takes it to a few cents. See `docs/coach.md` |
| Coach report, Fable 5.1 | $3.2292 | Picked from the Coach tab's model dropdown, 2026-09-22, over 249 matches at `effort: high`: 238,886 input / 15,206 output tokens and 8 web searches ($0.08). About 3.8× the Opus 5 run: 2× from the per-token price, the rest from 2.2× the billed input through the same `pause_turn` re-sends. Not a controlled comparison — it was the second report, so its prompt also carried the first. See `docs/coach.md` |

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

A `writer` can also be a paid plan's, which only a desktop shell would
know of; none exists, so every caller passes no plan and the app draws
the two cases above (`docs/frontend.md`, "Writing prose"). Nothing here
changes with it: with no credential configured, the `POST .../narrative`
routes still answer 503, and a plan's press would have to go through the
desktop shell, never through this API.

## The boundary a hosted proxy stays behind

This repository is proprietary (`LICENSE`), decided on 2026-10-01 "for
now", and it replaced an AGPL-3.0-only licence before any copy was
published. Outside contributions are not taken, so every line of it is
the maintainer's. A hosted tier, if one is built, puts a proxy between the
dashboard's generate buttons and Anthropic's API, holding the credential a
user would otherwise configure here. That proxy is a separate work, and
three lines keep it one:

- **The proxy imports nothing from this repository**, and lives in a private
  repository of its own. The client ships to every user and the proxy
  never does, so nothing of the proxy's (its credential handling, its
  budget rules) can leak through an installer. The separation is also what
  keeps "for now" cheap: if the client is ever opened again, under the
  AGPL or anything else, the proxy is not part of what is opened, and
  section 13 of the AGPL has nothing of the proxy's to reach.
- **The contract is documented, never shared as code.** Client and proxy
  agree on the Anthropic Messages API's request and response shape plus a
  small set of response headers. That description will live in this
  repository's docs once there is a proxy to describe. Neither side imports
  the other's types. The same description feeds the published schema that,
  with the in-app payload preview, carries the trust story a closed client
  no longer gets from its source being readable.
- **A piece both sides need goes in its own package** (a pricing table, a
  schema), depended on by both. Copying a file from here into the proxy is
  what this line exists to prevent: two copies drift, and a copy would tie
  the proxy to whatever licence this repository carries next.

No proxy exists yet. This section is here so that the day one is built, it
starts on the right side of these lines.

None of this loosens rule 5. Each of its four lines binds a call made
through a proxy as it binds one made directly:

- **No credential, no call.** Whatever a user configures to reach the proxy
  is a credential like the API key: resolved in `llm/config.py` and nowhere
  else, and with nothing configured every generate route still 503s.
  `llm/client.py` stays the only module that imports `anthropic`.
- **A button press, never a schedule.** The proxy changes where a call
  goes, not what starts one.
- **Cost is measured, never estimated**, from `response.usage`.
- **Loopback binds only.** The local app calls the proxy; nothing hosted
  calls into the local app.

A proxy is also a second recipient of match evidence. It would receive at
least the prompt a narrative route sends to Anthropic today. Whether it
receives more is decided when it is designed, and whatever it receives is
listed in this document before it ships. Three statements describe today's
arrangement and would stop being true, so building a proxy starts with
rewriting them: the exception at the top of this document, which names
Anthropic alone; rule 5's opening in AGENTS.md, which speaks of a Claude
credential; and "no account" in AGENTS.md's paragraph about the project.
If a proxy receives more than the prompt, three more join them: "no upload"
in that same paragraph, which the README and the dashboard's footer
repeat; the fourth promise in `SECURITY.md`, that no match data leaves the
machine except the prompt of a report; and the claim under "What calls
out, and what it sends" that two tests cover exactly what leaves the
machine.
