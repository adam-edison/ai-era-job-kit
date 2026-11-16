---
name: backlog
description:
  Manage this repo's Backlog.md tasks with the `backlog` CLI. Use when the user asks to create,
  find, view, plan, update, or finish tasks, or to work with Backlog drafts, docs, decisions, or
  milestones.
---

# Backlog.md

Load the project skill for Backlog rules when the repository has one. The project skill sets the
values that the backlog skill steps read:

- The base branch, such as `develop`, that each ticket branch starts from and merges into
- The protected branches, such as `develop` and `main`, that do not accept a push
- The ticket branch name, such as `abc-<n>-<short-slug>`
- The ticket title prefix, such as `ABC-<n>:`, at the start of each commit title and PR title
- The branch line budget and the aim of the budget, when the repository limits the lines that a
  branch changes

## Setup

1. Check that the CLI is available with `backlog --version`.
2. When the shell does not find the `backlog` command, install the CLI with `npm i -g backlog.md`.
3. Run `backlog instructions overview` once per conversation, before the first Backlog action.
4. Before task lifecycle actions, read the matching detailed guide:
   - `backlog instructions task-creation` before creating or splitting tasks
   - `backlog instructions task-execution` before planning, changing status or assignee, adding a
     plan or implementation notes, or implementing task work
   - `backlog instructions task-finalization` before checking acceptance criteria, writing final
     summaries, or moving tasks to terminal statuses
5. Run `backlog <command> --help` before unfamiliar commands. Help shows options, fields, and
   examples.

Do not edit Backlog task, draft, document, decision, or milestone markdown files directly. Use the
`backlog` CLI. The CLI updates the metadata, relationships, and history together.

## Closed and archived tasks

Do not view, search, or update Done or archived tasks unless the user asks. Do not read Done and
archived tasks during research, even when a closed task looks like a useful example, and filter each
task list to open statuses.

## Writing a task

Write task titles, descriptions, criteria, plans, notes, and summaries with the technical-voice
skill. Write the numbered steps of a plan with the skill-writing skill.

Acceptance criteria hold only what the user or a quoted source stated. Mark an inferred criterion
`[new]` so the user can strike the criterion.

List each known caveat, tradeoff, or side option in the description under "Open questions to decide
before implementation:", even when the user did not ask. The user decides each open question in
"Specifying a task". Work deferred to later goes in a separate ticket instead.

## Parent tasks

A parent task contains only the goal: title, description, and acceptance criteria for the outcome. A
parent task does not have an implementation plan, implementation notes, or details, and does not
list or describe the subtasks. Each detail lives in exactly one subtask, so there is no duplicate to
update.

## Creating a task

Give every new task a milestone with `-m <milestone id>`, including subtasks. Run
`backlog milestone list --plain` to see the milestones. Pick the milestone of a related open ticket,
or the milestone that matches the work. When no milestone fits, ask the user.

Commit each newly created task on the current working branch, so the task reaches the base branch
when that branch merges. Do not create a separate branch for the task. When the current branch is a
protected branch, create a new branch from the base branch for the task commit instead.

## Starting a task

Only a To Do task can be started. A claimed task with an unbuilt dependency stays on an open branch.
The next-ticket list offers the open branch as a resume choice. Check the dependencies of a task
before the claim:

1. Run `backlog task view <id> --plain`. Save each ticket that builds code that the task reads,
   changes, or calls as `needed_tickets`.
2. When `needed_tickets` contains a ticket that is not Done and is not a dependency of the task, add
   the ticket to the dependencies of the task with "Fixing a ticket".
3. When `needed_tickets` contains a ticket that is not Done, pick another task.

Several contributors can share a backlog, so claim a task before working on the task:

4. Run `git fetch --prune`.
   - GitHub deletes each ticket branch after the merge of the PR. The prune removes the local copy
     of each deleted branch.
5. Run `git branch -r --list "origin/<ticket branch name without the slug>*"`, such as
   `"origin/abc-12-*"`. Save the printed branches as `ticket_branches`.
6. Run `gh pr list --state open --search '"<ticket title prefix>" in:title'`, such as
   `'"ABC-12:" in:title'`. Save the printed PRs as `ticket_prs`.
   - A merged or closed PR does not count as a claim. A To Do task with a merged PR still needs
     work. An example is a task that a ticket-only PR created.
7. When `ticket_branches` or `ticket_prs` contains a result, pick another task. A matching branch or
   open PR shows that someone has claimed the task. Backlog's own task status does not show the
   claim. The task file on the base branch still shows To Do, and only the claimer's branch shows In
   Progress.
8. Create a new branch with the ticket branch name from the base branch.
9. Set the task to In Progress and assign the contributor's GitHub login
   (`gh api user --jq .login`), not `@claude`, with one `backlog task edit` command.
10. Commit only the task file as `<ticket title prefix> docs(backlog): start <summary>`.
11. Push the commit with `git push -u origin <branch>` before any other work. The pushed branch is
    the claim that the other contributors see.

Starting a task includes the whole flow through opening the PR:

12. Run "Specifying a task".
13. Work through the pr-review go-ahead without a question for the user.
    - Do not stop to ask before committing, pushing, finalizing the task, or opening the PR.
    - Stop only for a problem without a safe fix, such as a failing check without a known cause.

## Specifying a task

Right after the claim, the user answers the behavior questions of the task. The answers fix the
expected behavior. A resumed task already has the answers on the ticket branch, so a resumed task
does not run this section again.

1. Save each question below as `behavior_questions`:
   - Each item under "Open questions to decide before implementation:" in the description
   - Each acceptance criterion marked `[new]`, as a question whether the task needs the criterion
   - Each acceptance criterion that does not state an observable result of an action, such as a
     screen that the user sees or a file that a skill writes
2. Do not add a question about code structure, names, or libraries to `behavior_questions`.
   - The implementation skill decides each code question.
3. For each question in `behavior_questions`, drop each option that breaks the codebase, duplicates
   a rule, or has a known long-term cost.
   - For example, a task moves text to another file. The option that does not update each pointer to
     the moved text breaks the codebase. Each old pointer then leads to text that no longer exists.
     The option that updates each pointer is the only option left.
4. Save each question with only one option left, and the option, as `obvious_answers`.
5. Remove each question in `obvious_answers` from `behavior_questions`.
6. Tell the user each answer in `obvious_answers` in one line.
7. Ask the first question in `behavior_questions` with the decision format from CLAUDE.md.
   - Ask one question per message. A single message with every question overwhelms the user.
   - Give two to five options, as many as the question has real choices.
8. When the answer does not fix the observable result, ask a follow-up question with the decision
   format.
   - An example is the answer "show an error" without the text or the place of the error.
9. Ask each remaining question in `behavior_questions` with steps 7 and 8.
10. Write each answer from the user and each answer in `obvious_answers` as an acceptance criterion
    with "Writing a task".
11. Add each new criterion with `backlog task edit <id> --ac "<criterion>"`.
    - When an answer changes an existing criterion, replace the full list with
      `--acceptance-criteria`.
    - When the user accepts a `[new]` criterion, remove the `[new]` mark with
      `--acceptance-criteria`.
    - When the user strikes `[new]` criteria, pass every index in one command, such as
      `--remove-ac 2 --remove-ac 4`. A second command reads the indexes after the first removal.
12. Remove each answered item from the open questions of the description with `--description`.
13. When the project skill sets a branch line budget, estimate the reviewable lines that the task
    will change. Save the estimate as `task_estimate`.
14. When `task_estimate` is over the aim of the branch line budget, split the task with "Splitting a
    started task".
15. Commit the task file as `<ticket title prefix> docs(backlog): record the <summary> answers`.
16. Push the commit.

## Fixing a ticket

A ticket fix changes only ticket files, such as a missing dependency, a wrong status, or an archive.
Commit each ticket fix on the current working branch, with the ticket title prefix of the branch:

1. Make each fix with the `backlog` CLI.
   - `--dep` replaces the dependency list. Include the existing dependencies in the command.
2. Commit the ticket files.
3. Push the commit.

When the current branch is a protected branch, make the fix on a new branch instead:

1. Create a new branch called `ticket-fix-<short-slug>` from the base branch.
   - A branch with the ticket branch name of the fixed ticket reads as a claim on the fixed ticket.
2. Make the fix with steps 1 to 3 of the list in this section, with the ticket title prefix of the
   fixed ticket.
3. Open a PR with the open-pr skill.

## Planning a task

Before planning any custom code, look for a well-tested library that already does the job, unless
the repo already has one. Check each candidate's security record on Snyk
(`https://security.snyk.io/package/npm/<name>`) and the candidate's usage on npm (weekly downloads,
last publish, license). Present the candidates and findings to the user in the plan. Library code is
code that the contributors do not have to write or review.

Record `task_estimate` from "Specifying a task" in the plan, for example
`Estimated size: ~250 reviewable lines`.

## Splitting a started task

A started task already has a pushed branch. Each subtask starts a separate branch from the base
branch. Without a PR, the parent task branch stays on the remote and still claims the parent task.
The parent task branch merges in a separate PR before any subtask starts:

1. Read `backlog instructions task-creation`.
2. Create the subtasks on the parent task branch.
3. Commit the task files.
4. Push the commit.
5. Open a PR from the parent task branch with the open-pr skill.
   - The PR contains only the task file changes.
6. Stop, and ask the user to merge the parent task PR.
7. After the merge, start the first subtask from the base branch with "Starting a task".

## Committing and pushing

Push right after every commit on a ticket branch, using `git push -u origin <branch>` the first
time. Do not push to a protected branch.

## Skill changes

Commit each change to a skill under `.claude/skills` on the current ticket branch, with the ticket
title prefix of the branch in the commit title. The current PR then includes the skill change. Do
not create a separate ticket, branch, or PR for a skill change, and do not ask the user where the
skill change goes. When the current branch is a protected branch, create a new branch from the base
branch for the skill change instead.

## Finishing a task

Once the work is verified, finalize the task yourself:

1. Read `backlog instructions task-finalization`.
2. Check each acceptance criterion of the finished task.
3. Write the final summary.
4. Set the finished task to Done.
5. Check each acceptance criterion of the parent task that the finished subtask satisfies.
6. Set the parent task to Done once every subtask of the parent task is Done.
7. Update each task that depends on the finished task.
8. Commit the task files as `<ticket title prefix> docs(backlog): <summary>`.
9. Push the commit.
10. Tell the user which acceptance criteria were checked and which statuses were set.
11. Open the PR against the base branch with the open-pr skill.

Each ticket gets a separate branch and PR. After opening the PR, stop. Never ask whether to start
another ticket.
