---
name: skill-writing
description:
  Write the steps of a skill in this repo. Use when writing or changing a skill under
  .claude/skills, or the numbered steps of a ticket plan.
---

# Skill writing

Write the prose of each step with the technical-voice skill.

## One action per step

A reader who follows a numbered list takes each number as one action. An action inside a longer step
is easy to miss. Give each action in a numbered list a separate step. A condition and the action
that the condition triggers make one step.

```text
Before:
5. Commit the task files and push the commit.

After:
5. Commit the task files.
6. Push the commit.
```

A step that runs one command for two settings stays one step, such as one `backlog task edit`
command that sets the status and the assignee.

Refer to a step in the same list by the step number, such as "run steps 3 to 6 without asking".

## Checklist for a long procedure

For a long procedure, write a numbered checklist of the steps first, then a `Step N` heading for
each step's details. The checklist shows every step before the reader starts. The
[Anthropic skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
recommend the checklist pattern. A `Step N`
reference refers to a step of the same checklist.

## Saved results

A reader of "the branches from step 2 of Find the startable tickets" has to find the step in another
section to learn what the branches are. Save each result that a later step reads as a snake_case
name in backticks. A result can be a command output or a list of tickets. Each later step reads the
result by the same name. The underscores tell a saved result apart from a command, a path, or prose.

```text
Before:
3. Run `gh pr list --state open`.
4. Drop each ticket that has a PR in the `gh pr list` output.

After:
3. Run `gh pr list --state open`. Save the listed PRs as `open_prs`.
4. Drop each ticket that has a PR in `open_prs`.
```

## Reread the steps

After writing, reread the steps once for each problem below, and rewrite each step with the problem:

1. A numbered step with more than one action
2. A step that reads an earlier result without the snake_case name of the result
