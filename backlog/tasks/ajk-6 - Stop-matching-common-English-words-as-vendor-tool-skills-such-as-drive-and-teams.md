---
id: AJK-6
title: >-
  Stop matching common English words as vendor tool skills, such as drive and
  teams
status: To Do
assignee: []
created_date: '2026-11-16T10:04:00Z'
labels: []
milestone: m-0
dependencies: []
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A resume score run with saved postings lists Google Drive, Microsoft Teams, Microsoft Office, Microsoft Project, Microsoft Access, Google Meet, and Component object model COM software among the lane skills, with demand weight from the postings. None of the postings asks for those tools.

`build_vocab` in `scripts/jobdata/lexicon.py` strips the vendor name from each O*NET name and adds the rest as an extra alias when it has at least 3 characters. "Google Drive" gets the alias `drive`, "Microsoft Teams" gets `teams`, "Google Meet" gets `meet`, "Microsoft Office" gets `office`, "Microsoft Project" gets `project`, and "Microsoft Access" gets `access`. Each of those is a common English word in job postings and resumes. The trailing-acronym rule adds `com` for "Component object model COM software", which matches every `.com` address and company name. Posting frequency then gives these tools real weight in the lift list.

Made-up sample text that reproduces the problem:

```text
Drive impact across teams. Meet with the project office to plan access control for example.com.
```

Open questions to decide before implementation:

- Should the vendor-stripped alias apply only when the remaining word is not a common English word, or only when the full name appears?
- Should the trailing-acronym alias skip `com`, or require the acronym to appear in capitals?
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 [new] Sample text with drive, teams, meet, office, project, and access as plain words finds none of the matching vendor tools
- [ ] #2 [new] Sample text with example.com finds no Component object model COM skill
- [ ] #3 [new] Sample text with Google Drive and Microsoft Teams still finds both tools
- [ ] #4 [new] A test in tests/test_kit.py checks each case
<!-- AC:END -->
