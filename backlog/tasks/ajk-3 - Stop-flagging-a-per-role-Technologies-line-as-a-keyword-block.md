---
id: AJK-3
title: Stop flagging a per-role Technologies line as a keyword block
status: To Do
assignee: []
created_date: '2026-11-15T06:24:00Z'
updated_date: '2026-11-15T06:37:00Z'
labels: []
milestone: m-0
dependencies: []
type: bug
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The Screen Grade reports "Keyword block outside Skills" for each `Technologies:` line under an Experience role. Staffing recruiters ask for a technologies line under each role, so a candidate who follows the request gets one stuffing flag per role.

`manipulation_flags` in `scripts/screen_grade.py` splits each line on commas, pipes, semicolons, and bullets. The function reports a keyword block for any line with 12 or more items outside the `skills`, `technical skills`, and `header` sections. A labeled technologies line for a role with 12 or more tools reaches the limit.

Made-up sample lines that reproduce the problem:

```text
Senior Software Engineer, Acme Corp, 03/2018 — 06/2022
- Built the billing API in Node.js and PostgreSQL.
Technologies: Node.js, TypeScript, Express, PostgreSQL, Redis, Docker, AWS Lambda, AWS SQS, AWS S3, Jest, GitHub Actions, Terraform
```

Open questions to decide before implementation:

- Which labels mark a technologies line, such as `Technologies:`, `Tech stack:`, and `Tools:`?
- Should a labeled line still get a flag when the line contains tools that no bullet of the same role mentions?
- Should the labeled line still get a softer note, instead of no note, because some screeners read a long tool list as stuffing?
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 [new] A `Technologies:` line with 12 or more items under an Experience role does not produce a keyword block flag
- [ ] #2 [new] A line with 12 or more items and without a technologies label in an Experience section still produces a keyword block flag
- [ ] #3 [new] A test in `tests/test_kit.py` checks the labeled line and the unlabeled line
<!-- AC:END -->
