---
id: AJK-4
title: Match plural forms of skill search words, such as microservices
status: To Do
assignee: []
created_date: '2026-11-16T01:20:00Z'
labels: []
milestone: m-0
dependencies: []
type: bug
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The LinkedIn score reports Microservices as a resume skill that LinkedIn does not show, for a profile with "microservices" in two Experience bullets.

`_pattern` in `scripts/jobdata/lexicon.py` wraps each alias in word boundaries. The boundary after the alias rejects a trailing "s". The Microservices alias is `microservice`, so `microservices` does not match. A resume with the singular word once then shows Microservices, and a profile with only the plural does not. The consistency check in `scripts/linkedin_score.py` then reports a false gap.

Other singular aliases can fail the same way, such as `rest api` against "REST APIs" in lowercase text.

Made-up sample text that reproduces the problem:

```text
Split the order system into 6 microservices.
```

Open questions to decide before implementation:

- Should `_pattern` accept an optional trailing "s" on every alias, or should each affected alias in `CURATED` list the plural form?
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 [new] The made-up sample text in the description shows Microservices as a found skill
- [ ] #2 [new] Lowercase "rest apis" shows REST APIs as a found skill
- [ ] #3 [new] A test in `tests/test_kit.py` checks the plural matches
<!-- AC:END -->
