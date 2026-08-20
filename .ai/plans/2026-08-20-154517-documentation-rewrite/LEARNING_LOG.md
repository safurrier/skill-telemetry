---
id: plan-learning-log
title: Learning Log
description: Observations gathered during the documentation rewrite.
---

# Learning log—documentation-rewrite

- The original README had accurate privacy and command claims, but its reader path
  jumped from installation to a command inventory without an evidence mental model.
- The public docs had more contributor scaffolding than operator guidance; tutorial,
  how-to, and reference indexes were placeholders.
- Source review corrected one important overclaim: skill events may retain namespaced
  SHA-256 pseudonyms, while raw session and turn identifiers remain excluded.
- The public-history scanner checks selected reachable objects but does not enforce
  the one-parentless-commit release policy.
- CLI help confirms port 0 is not documented even though source validation accepts it;
  public docs continue to recommend normal numbered ports rather than widen that claim.
- The writing checker helped locate dense prose and mechanical issues. Product names,
  protocol acronyms, proper runtime names, and exact technical terms remain when they
  improve searchability or preserve the contract.
