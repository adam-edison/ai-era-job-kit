---
id: AJK-5
title: Fail the pinned-artifacts check when the portfolio record has no artifacts
status: To Do
assignee: []
created_date: '2026-11-16T02:17:00Z'
labels: []
milestone: m-0
dependencies: []
type: bug
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The GitHub score passes "Portfolio artifacts are the pinned repos" for a `portfolio.json` with an empty `artifacts` list. The check then adds points for a match that does not exist.

`score` in `scripts/github_score.py` builds `unpinned` from the artifacts that have a `repo` field. An empty `artifacts` list gives an empty `unpinned` list, and the check passes on `not unpinned`.

Open questions to decide before implementation:

- Should the check fail, or should the scorer leave the check out and report "not checked", when the record does not have any artifacts with a repo?
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 [new] A `portfolio.json` with an empty `artifacts` list does not pass the pinned-artifacts check
- [ ] #2 [new] A test in `tests/test_kit.py` checks the empty artifacts case
<!-- AC:END -->
