---
id: AJK-2
title: Stop matching the Ext JS skill inside Node.js
status: To Do
assignee: []
created_date: '2026-11-15T06:24:00Z'
labels: []
milestone: m-0
dependencies: []
type: bug
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The resume score reports "Ext JS appears 19 times" as keyword stuffing for a resume that never mentions Ext JS. The resume contains `Node.js` 19 times. The score also counts Ext JS as a skill on the resume, so the candidate can get questions about a framework the candidate never used.

The O*NET technology list for Software Developers (15-1252.00) includes "Ext JS". `build_vocab` in `scripts/jobdata/lexicon.py` adds the last word of an O*NET name as an extra alias when the last word is in capitals, so that "Extensible markup language XML" also matches "XML". For "Ext JS", the rule adds the alias `js`. `_pattern` treats a period as a word boundary, so `js` matches the end of `Node.js`, `Next.js`, `React.js`, and `Express.js`. `manipulation_flags` in `scripts/screen_grade.py` then sums the alias matches and reports the stuffing flag over 10 matches.

Made-up sample text that reproduces the problem:

```text
Built REST APIs in Node.js and Express.js, with a Next.js admin app.
```

Open questions to decide before implementation:

- Should the trailing-acronym alias require at least 3 characters, or should `_pattern` treat a period before the alias as part of the word?
- Do other O*NET names in the lane produce the same kind of short alias, and should the fix apply to each of those names?
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 [new] A resume that contains `Node.js` and does not contain `Ext JS` does not report Ext JS as a found skill
- [ ] #2 [new] A resume that contains `Node.js` more than 10 times does not report an Ext JS stuffing flag
- [ ] #3 [new] "Extensible markup language XML" still matches a resume that contains `XML`
- [ ] #4 [new] A test in `tests/test_kit.py` checks the Ext JS case and the XML case
<!-- AC:END -->
