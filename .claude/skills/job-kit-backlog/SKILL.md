---
name: job-kit-backlog
description:
  AI-Era Job Kit rules for Backlog.md tickets, on top of the backlog and next-ticket skills. Use with
  the backlog skill whenever creating, starting, planning, splitting, finishing, or changing a kit
  ticket (IDs like AJK-1). Use with the next-ticket skill whenever the user asks for the next ticket.
---

# Job kit backlog

Follow the backlog skill and the next-ticket skill with the values and rules in the job-kit-backlog
skill.

## Remotes

The repository has two remotes:

- `fork` is the user's fork, `adam-edison/ai-era-job-kit`. Every ticket branch and push goes to
  `fork`.
- `origin` is the upstream repository, `Vets-Who-Code/ai-era-job-kit`. Do not push to `origin`.

Replace `origin` with `fork` in each git command from the backlog and next-ticket skills, such as
`git push -u fork <branch>` and `git pull fork develop`.

## Backlog skill values

- Base branch: `develop`
- Protected branches: `main`
- Ticket branch name: `ajk-<n>-<short-slug>`, such as `ajk-1-fix-years-parse`
- Ticket title prefix: `AJK-<n>:`, such as `AJK-1:`
- Branch line budget: none

## Next-ticket skill values

- Base branch: `develop`
- Install command: none
- Lockfile: none
- Ticket list command: none

## Tests

Run the test suite with `python3 -m unittest discover -s tests -v` from the repository root. Run the
suite before each commit that changes code under `scripts/`, and before opening a PR.

## Ticket branches without PRs

Each ticket gets a ticket branch. The kit repository does not use PRs for ticket work. A ticket
branch merges into `develop` on the local machine instead. Where the backlog skill reads a PR, a
`gh` command, the open-pr skill, or the pr-review skill, follow the steps below instead.

Start a ticket:

1. Run `git checkout develop`.
2. Run `git pull fork develop`.
3. Run `git checkout -b <ticket branch name>`.
4. Set the task to In Progress with `backlog task edit <id> -s "In Progress"`.
5. Commit only the task file as `<ticket title prefix> docs(backlog): start <summary>`.
6. Push the branch with `git push -u fork <branch>`.
7. Run "Specifying a task" from the backlog skill.

Do the work in small commits on the ticket branch. Push after each commit.

Finish a ticket:

1. Run the test suite.
2. When a test fails, follow the test failure rules in the user's CLAUDE.md.
3. Run "Finishing a task" from the backlog skill, without the PR step.
4. Ask the user before the merge into `develop`.
5. Run `git checkout develop`.
6. Run `git pull fork develop`.
7. Run `git merge --no-ff <branch>`.
8. Run the test suite again when the merge changed any file under `scripts/` or `tests/`.
9. Run `git push fork develop`.
10. Run `git branch -d <branch>`.
11. Run `git push fork --delete <branch>`.

## Upstream PRs

A PR to `Vets-Who-Code/ai-era-job-kit` publishes the change. Do not open an upstream PR unless the
user asks for one. An upstream PR does not include `backlog/` or `.claude/`.

## Private data

The repository and every ticket are public. A ticket, test fixture, commit message, or PR body uses
made-up sample text. Do not copy text from the user's resume, LinkedIn, or `resume-work` repository.

## Planned tasks

Planned is a custom status in `backlog/config.yml` for work decided for later that is not ready to
start. To find work, list only To Do tasks (`backlog task list --status "To Do" --plain`). Do not
start, plan, or update a Planned task unless the user asks. Search Planned tasks only to avoid
creating a duplicate.

When a decision defers work to later, create a ticket for the deferred work with `-s Planned`
instead of mentioning the work inside another ticket. Link the new ticket to the ticket that the
work builds on with `--dep`, not as a subtask.
