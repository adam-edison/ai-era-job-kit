---
name: next-ticket
description:
  Offer five tickets to resume or start next in this repo. Use when the user asks for the next
  ticket, what to work on next, or which ticket to pick up.
---

# Next ticket

Load the project skill for next-ticket rules when the repository has one. The project skill sets the
values that the next-ticket skill steps read:

- The base branch, such as `develop`
- The install command, such as `npm install`
- The lockfile that the install command changes, such as `package-lock.json`
- The ticket list command, such as a package script, that prints up to five tickets in the order to
  offer
- The order rules of the ticket list command, and each mark that the command prints

Without a ticket list command, list the To Do tasks with
`backlog task list --status "To Do" --plain`. Offer the first five tasks, and do not run the resume
steps.

## Refresh the base branch first

A stale branch offers tickets that already merged and misses new ones. Before reading any tickets:

1. Run `git status --porcelain`.
2. When the `git status` output shows changes, stop and ask the user what to do with the changes.
3. Run `git checkout <base branch>`.
4. Run `git pull origin <base branch>`.
5. Run the install command, so packages added on the base branch are installed before a commit hook
   needs the packages.
6. When the install command changes the lockfile, do not commit the lockfile on the base branch.
   Commit the lockfile on the ticket branch after the start commit of a new ticket, or after
   `git checkout <branch>` of a resume ticket.
7. Run `git fetch` so the remote branch list shows every branch on GitHub.

Run steps 3 to 6 without asking the user.

## Find the choices

1. Run the ticket list command. Save the printed tickets as `script_choices`.
2. For each ticket in `script_choices` with the resume mark, run
   `git diff --name-only origin/<base branch>...<branch> -- backlog/tasks` with the branch that the
   command prints. The start commit changes the ticket file. Save the file with the ticket ID as
   `ticket_file`.
3. For each resume ticket, run `git show "<branch>:<ticket_file>"`. Read the next step in the
   Implementation Notes, such as a PR that the ticket waits on.

A resume ticket has a remote branch without a PR in any state, and the git user wrote the last
commit on the branch.

## Offer five choices

Label the choices in `script_choices` A through E. Each choice shows the ticket ID, title, and a
one-line summary of what the ticket does, read from `backlog task view <id> --plain`. Below the
summary, each choice shows the milestone, labels, and type line from `script_choices`. Show each
mark that `script_choices` prints, such as the resume mark. For a resume choice, show the next step
from the ticket notes instead of the summary. Put a blank line before each letter so the choices are
easy to tell apart. Do not show size estimates; sizing belongs to planning the ticket.

```text
A. ABC-12 (resume) - Add a user repository
   Waits on PR #40. After the merge, merge the base branch into the ticket branch.
   Milestone: 03 Source code structure · Labels: server · Type: chore

B. ABC-14 - Add a settings page
   Adds a settings page where the user picks the theme.
   Milestone: 04 Settings · Labels: web · Type: feature
```

## Start the chosen ticket

When the user picks a resume ticket, run `git checkout <branch>`, `git pull`, and the install
command, then follow the next step in the ticket notes.

When the user picks any other ticket, follow "Starting a task" in the backlog skill.
