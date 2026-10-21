---
paths:
  - "AUTHORS"
  - "scripts/privacy_scan.py"
---

# Working on the privacy scan: the one public identity

The one public identity is the maintainer's handle, in `AUTHORS` and nowhere else;
the scan exempts that file for that one category (`git-account`), and for a
git-name hit that equals the scanned clone's own declared `user.name` (the
public clone commits as the handle), so the handle anywhere else is still a
finding.
