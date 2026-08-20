---
id: skill-telemetry-decision-ledger
title: skill-telemetry decision ledger
description: Chronological record of durable product and repository decisions.
index:
  - id: public-history
    keywords: [release, history, privacy, refs]
  - id: documentation-authority
    keywords: [docs, spec, architecture, reference]
---

# Decision ledger

This ledger records decisions that affect the public product or repository
boundary. Newer entries appear first. A standalone ADR holds decisions that need
more context, alternatives, or consequences.

## 2026-08-20—Rewrite public documentation around operator tasks

- **Plan:** `documentation-rewrite`
- **Decision:** make the root README the shortest product journey, route operator
  tasks through tutorials and how-to guides, keep normative behavior in `SPEC.md`,
  and use reference pages for stable command, state, and support facts.
- **Why:** the initial docs routed readers into contributor scaffolding while
  leaving the tutorial, how-to, and reference folders as placeholders.
- **Boundary:** `AGENTS.md`, `.ai/plans/`, and review workflow remain contributor
  material. They don't define product behavior.
- **Proof:** documentation tests cover every authored page. Command examples are
  checked against CLI help, source, and focused tests. Repository writing checks
  remain advisory.

## 2026-08-19—Publish a scrubbed, parentless v0.1.0 repository

- **Decision:** recreate the public repository from one reviewed parentless commit
  and publish the first release as `v0.1.0`.
- **Why:** the first repository object store contained a source-level privacy
  denylist with contributor-specific markers. Rewriting refs hid the old commit
  from normal history but left it addressable by SHA, so the repository was
  deleted and recreated.
- **Boundary:** the public remote now exposes one `main` commit and one release
  tag. Local development and archive refs aren't publication refs.
- **Proof:** the removed SHAs no longer resolve through the GitHub commit API. The
  reachable-history scan, Python and Pi suites, isolated Git installs, artifact
  checks, and public CI passed at the recreated commit.

## 2026-08-19—Scan every object reachable from publication refs

- **Decision:** scan blobs plus commit and annotated-tag text reachable from each
  explicitly selected publication ref.
- **Why:** checking only the working tree or tip commit can miss a private path,
  credential-shaped string, unsafe link, generated directory, or oversized blob
  in reachable history.
- **Enforcement:** `scripts/verify_public_history.py` implements the scan, and
  `mise run public-history` invokes it for an explicit ref. The scanner doesn't
  enforce a one-commit history. The parentless-release shape is release policy.
- **Release policy:** select only intended public refs, use reviewed full commit
  SHAs or release tags for installation, and don't publish local archive refs.
  Python and Pi remain Git-only. The project makes no PyPI or npm release claim.
