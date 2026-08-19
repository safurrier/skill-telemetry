# Slice Artifact Policy

Use this policy when deciding what belongs in a plan directory.

## Durable Context

Keep these in git when they are part of the slice contract:

- `META.yaml`
- `SPEC.md`
- `IMPLEMENTATION.md`
- `TODO.md`
- `DECISIONS.md`
- `LEARNING_LOG.md`
- `VALIDATION.md`
- `REVIEW.md`
- `artifacts/manifest.yaml`
- short validation or review reports referenced by the manifest
- concise command transcripts when they are easier to audit than prose
- screenshots when visual evidence matters
- rendered prompts under `prompts/` when they explain the handoff

## Scratch Evidence

Do not commit these by default:

- raw transcripts
- huge generated diffs
- temporary screenshots or videos
- unreviewed generated patches
- local handoff drafts
- one-off research notes

If scratch evidence matters, summarize it into `VALIDATION.md`, `REVIEW.md`, or a
short artifact report and declare that report in `artifacts/manifest.yaml`.

Every manifest entry is a promise: the referenced path must exist, stay inside
the plan directory, be tracked or staged for commit, and be small enough for a
reviewer to open directly.

## Handoff Rule

A future human or agent should be able to answer:

1. What changed?
2. Why did it change?
3. What was validated?
4. What still worries us?
5. Where is the evidence?
