# web — sensei-top dashboard

Vite + React + TypeScript (strict), Tailwind v4, TanStack Query v5, recharts.
`react-router` serves every page at an address; `src/routes.tsx` is the table
of them ([docs/frontend.md](../docs/frontend.md), "The shell").

    pnpm install
    pnpm dev          # :5173, proxies /api to the FastAPI server on :8000
    pnpm build        # typecheck + build into ../src/sensei_top/web_dist/, which `sensei-top serve` serves
    pnpm lint
    pnpm gen:types    # regenerate src/types/api.ts from the API's OpenAPI schema

`src/types/api.ts` is generated but committed, so the frontend builds without a
Python environment. Re-run `pnpm gen:types` after changing a response model in
`src/sensei_top/api/models/` — the build then fails on any field the UI still
expects, rather than rendering `undefined`.

## Colors

`src/index.css` holds every colour as a CSS custom property, `src/theme.ts`
the chart-facing ones again as hex, and `../scripts/validate_palette.py` a
third time. The duplication is needed: recharts writes SVG presentation
attributes, which do not resolve `var()`. `tests/test_palette.py` fails when
the three disagree.

The palette is dark only. The categorical slots (blue `self` → you, orange
`opponent` → the opponent, green `field` → the field and your lands) are
validated for colour-blind separation and contrast by `validate_palette.py`.
Slots follow the entity, never its rank, so filtering never repaints a series.
[docs/design-system.md](../docs/design-system.md), "Palette", has every token.
