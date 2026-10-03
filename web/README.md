# web — sensei-top dashboard

Vite + React + TypeScript (strict), Tailwind v4, TanStack Query v5, recharts.
Three views behind a tab component; no router in the MVP.

    pnpm install
    pnpm dev          # :5173, proxies /api to the FastAPI server on :8000
    pnpm build        # typecheck + build into dist/, which `sensei-top serve` serves
    pnpm lint
    pnpm gen:types    # regenerate src/types/api.ts from the API's OpenAPI schema

`src/types/api.ts` is generated but committed, so the frontend builds without a
Python environment. Re-run `pnpm gen:types` after changing a response model in
`src/sensei_top/api/app.py` — the build then fails on any field the UI still
expects, rather than rendering `undefined`.

## Colors

`src/theme.ts` holds the chart palette and `src/index.css` the same values as
CSS custom properties. Both are needed: recharts writes SVG presentation
attributes, which do not resolve `var()`. Keep them in step.

The categorical slots (blue → you, orange → opponent, aqua → lands) were
validated for colorblind separation and contrast in both light and dark mode.
Slots follow the entity, never its rank, so filtering never repaints a series.
Aqua sits below 3:1 on the light surface, which is why every chart also ships a
legend and a table of its numbers.
