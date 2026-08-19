---
id: skill-telemetry-decision-ledger
title: skill-telemetry Decision Ledger
description: Append-only durable decisions for skill-telemetry.
---

# Decision Ledger

## 2026-08-19 — public-release-history

- **Decision:** publish only a one-commit public root and scan every blob
  reachable from the refs selected for publication before release.
- **Why:** a clean checkout is insufficient when earlier reachable commits can
  retain private provenance or credential-shaped material.
- **Boundary:** local archive refs and release-validation evidence remain local;
  they are not publication refs. The scanner rejects private markers,
  credential-shaped content, unsafe Git modes, generated paths, and oversized
  blobs.
- **Release:** build and install checks run from a temporary single-branch clone
  of public `main`. Git installation uses a reviewed full commit SHA or release
  tag. Python and Pi remain Git-only; no package-registry publication is claimed.
