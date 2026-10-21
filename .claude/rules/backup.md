---
paths:
  - "src/sensei_top/backup/**"
---

# Working in `backup/`: where a snapshot may be kept

A `[backup] dir` pointing inside the repo but outside `data/` would
put real match history where git can see it — the
`*.db.backup`/`*.db.backup.[0-9]*` gitignore entries cover the default
naming, but a location the user chooses is theirs to keep out of the tree.
