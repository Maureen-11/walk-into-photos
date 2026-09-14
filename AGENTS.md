# Project instructions

## Scope

This repository is the student prototype for “走进照片”. The current target is the Luna execution plan: eight photo categories, four shared scene engines, local-first planning, a user-confirmed template, progressive quality modes, and an offline-shareable scene package. Any feature not in the current plan remains deferred.

## Working rules

- Preserve user changes; inspect `git status` before editing.
- Do not add deferred features (phone, hand gestures, audio, multi-photo exhibitions, movie scenes) to this release.
- Do not claim real 3D reconstruction. Clearly label AI-estimated or procedurally completed unseen areas.
- Do not call online chat APIs or upload user photos. The planner must use the pinned local Moondream model or a clearly labelled local-rules fallback.
- Keep generated artifacts and private photos out of Git.
- Prefer small, reviewable commits and meaningful verification.

## Validation language

Distinguish `mock/demo`, local-rules fallback, and real model-backed behavior in code, UI, and documentation.
- Every Luna task must state its allowed modules, forbidden modules, input/output, validation command, visual checks, rollback, and evidence.
