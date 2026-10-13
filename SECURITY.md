# Security

## Reporting a vulnerability

Write to **contact@senseitop.com**. Please do not open a public issue for
something you believe can be exploited.

Say what you did, what happened, and the version or commit you ran. A proof
of concept helps. Your database, your log and your config file are never
needed, and the config file can hold an API key, so do not send them.

This project has one maintainer, who answers in their spare time. There is
no promised response time. A fix credits the person who reported it, unless
they ask otherwise.

## What this application promises

Sensei Top runs on your machine, reads log files the game clients already
write, and serves a dashboard on loopback. Its security rests on four
promises. A way to break any of them is what we most want to hear about:

1. **The server listens on loopback only**, and refuses to start on any
   other address.
2. **Another website cannot use the local API.** Any page open in your
   browser can send requests to `127.0.0.1`. The server refuses a foreign
   `Host` or `Origin`, and refuses any request that changes something
   unless it carries the dashboard's own header
   (`src/sensei_top/api/guard.py`).
3. **Nothing calls a paid API without a configured key and a button
   press.** Anything that makes the application call a paid API on its
   own, on a schedule, or on another page's behalf is a vulnerability.
4. **No match data leaves the machine**, except the prompt of a report the
   user asked to generate ([docs/llm.md](docs/llm.md)).

Also in scope: a crafted log file, or a crafted file from one of the
download sources, that makes the application run code or write outside its
own database and cache.

## Out of scope

- Anything that needs an attacker who already runs code as your user or
  can already read your files.
- The game clients, and the services this application downloads reference
  data from. Report those to their owners.
- Denial of service against the local server by a process on the same
  machine.
- The development server (`pnpm dev`), which is not what users run.

## Supported versions

Only the latest release receives fixes; the app updates itself, and there
is no long-term branch. A fix for one of the promises above ships on its
own, outside the normal cadence.
