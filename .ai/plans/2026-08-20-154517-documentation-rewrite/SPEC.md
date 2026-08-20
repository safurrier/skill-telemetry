---
id: plan-spec
title: Task Specification
description: Requirements and constraints for the public documentation rewrite.
---

# Specification—documentation-rewrite

## Problem

The initial public docs contain accurate fragments but lack a coherent reader path.
Placeholder intent folders and generic rubrics crowd out install, operate, inspect,
privacy, support, and troubleshooting guidance.

## Requirements

### Must

- Rewrite the root README with README Improver and verified commands.
- Rewrite every authored public page under `docs/` plus root `SPEC.md`.
- Preserve exact product boundaries, privacy claims, failure semantics, commands,
  paths, links, versions, and unsupported states unless source evidence corrects them.
- Correct the raw-session overclaim while preserving pseudonymous correlation rules.
- Provide useful tutorial, how-to, explanation, and reference navigation.
- Run the writing checker separately on every exact candidate.
- Meet FRE 55 and FK 10 for every normal readability sample within three passes, or
  document why precision prevents it.
- Require independent semantic-preservation review before publication.

### Should

- Keep the README concise by linking to deeper operator reference.
- Tailor review rubrics to this project's real contracts and command-line surface.
- Add tests for all authored doc frontmatter, IDs, local links, and scaffold text.

## Constraints

- Do not edit `AGENTS.md`, `CLAUDE.md`, vendored `.agent` material, plan templates,
  fixtures, generated files, or copied third-party documentation as part of the prose
  sweep.
- Do not invent registry publication, Pi commands, service behavior, configuration,
  authentication, or support claims.
- Do not run host-mutating or external-service examples merely to validate prose.
