---
id: AJK-1
title: Read MM/YYYY end dates in every date check
status: To Do
assignee: []
created_date: '2026-11-15T06:24:00Z'
updated_date: '2026-11-15T06:37:00Z'
labels: []
milestone: m-0
dependencies: []
type: bug
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The Screen Grade and the resume score misread a resume with numeric month dates. A resume with roles dated from `05/2007` to `Present` reports "about 3 years of dated Experience roles". A posting that asks for 5+ years then fails the knockout for a candidate with 19 years.

`DATE_RANGE` in `scripts/screen_grade.py` accepts a month name before each year, such as `June 2025`. `DATE_RANGE` does not accept a numeric month before the end year, such as `06/2025`. A role dated `03/2024 — 06/2025` does not match. A role dated `04/2023 — Present` matches, because `Present` does not need a month.

Each check below reads `DATE_RANGE`, so each check sees only the roles that end in `Present`:

- `total_years` in `scripts/screen_grade.py` counts the years for the years knockout.
- The "Dates parse" row of the parse gate in `scripts/screen_grade.py` counts the date ranges. The row reports 1 date range for a resume with 12 roles.
- `role_spans` in `scripts/resume_score.py` assigns each line to the role above the line. Every line under an unmatched role gets the span of the last matched role. A skill from a role that ended over 5 years ago then grades as recent instead of stale.
- `chronology` in `scripts/resume_score.py` reports gaps over 6 months and roles under a year.
- The reverse chronological order rule in `scripts/screen_grade.py` compares the end dates in each section.

Made-up sample lines that reproduce the problem:

```text
Acme Corp, Springfield, IL · Remote, 04/2023 — Present
Globex, Springfield, IL · Remote, 03/2018 — 06/2022
Initech, Springfield, IL, 05/2010 — 01/2018
```

Open questions to decide before implementation:

- Should the date check also read other numeric formats, such as `2025-06` and `06/25`?
- Should the start date also accept a numeric month on every format that the end date accepts?
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 [new] A role dated `03/2018 — 06/2022` adds 4 years to the years count
- [ ] #2 [new] The made-up sample lines in the description report the same years count as the same roles written with month names, such as `March 2018 — June 2022`
- [ ] #3 [new] The parse gate reports 3 date ranges for the made-up sample lines
- [ ] #4 [new] A skill that appears only under the `Initech` role grades as stale
- [ ] #5 [new] A test in `tests/test_kit.py` checks the years count, the date range count, and the stale grade for MM/YYYY end dates
<!-- AC:END -->
