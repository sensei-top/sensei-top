---
paths:
  - "desktop/**"
---

# Working in `desktop/`: the Electron shell's files

`src/main.ts` is the only main-process file that loads Electron; `server.ts` runs `serve` with its stdin as a lifeline, `window.ts`, `tray.ts`, `log.ts` (the server log's format, in `logs/shell.log`), `store.ts` (`shell.json`); `server/` freezes the server with PyInstaller — `desktop/README.md` for the build steps, `docs/desktop.md` for the design.

    pnpm --dir desktop dev     # the Electron shell on this checkout (Linux only: its script uses `env -u`)
