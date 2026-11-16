---
name: technical-voice
description:
  Write prose in this repo in a technical voice. Use when writing or changing code comments, test
  titles, docs, skill text, ticket descriptions, commit messages, PR bodies, or PR replies.
---

# Technical voice

Write code comments, test titles, docs, skill text, ticket descriptions, commit messages, PR bodies,
and PR replies in a technical voice.

## Rules

- Use short declarative sentences in the active voice. State what the code does and why.
- State the subject. Do not use pronouns without a noun, even when the noun appears earlier in the
  same sentence.
- Do not describe benefits in loose terms. State the mechanism instead.

## Pronouns to avoid

- it
- its
- them
- they
- their
- this, when no noun follows, as in "this is"
- that, when no noun follows, as in "that means"

"This check" and "that file" are fine, because a noun follows the word.

Before:

```text
Only vite-plugin-pwa can supply this virtual module, and the tests run without it.
```

After:

```text
Vitest does not load vite-plugin-pwa, so virtual:pwa-register/react does not exist in tests.
```

## Forbidden words

- by hand: "the app sets the cookie by hand" does not state which code or which person does the
  work, or which default the work replaces. State the actor and the action, such as "the ApiClient
  adds the Cookie header", "the user types the value", or "the Claude session runs the command".
- cover, covers, covered, covering: "the search covers every subfolder" does not state whether the
  code reads, checks, includes, or changes each subfolder. Use the verb for what the code does, such
  as reads, checks, includes, or applies to.
- holds: "the file holds the default values" does not state whether the code wrote, stores, or reads
  the content. Use the verb for what the code does, such as contains, stores, or returns.
- lists, listed, listing: "the error lists DEPLOYMENT" implies several items and does not state
  whether the code shows, reports, or returns the item. Use the verb for what the code does, such as
  shows, reports, returns, or contains. The plural noun stays allowed right after the, both, two, or
  word, as in "both lists" and "the word lists".
- name the, names the, named, naming: "the error names the file" does not state whether the error
  shows or reports the file. Use the verb for what the code does, such as shows, reports, or
  includes. Write "called" instead of "named", as in "a file called setup.ts". The plural noun
  "names", as in "table names", stays allowed.
- nobody: "code nobody has to write" does not state which person the sentence means. State who, such
  as the user, the reviewer, or the contributors.
- guess, guesses, guessed, guessing: "a guessed database" does not state where the value comes from.
  State the source, such as a default value, an environment variable, or the first match.
- keep, keeps, kept, keeping: "the filter keeps the mixed value" does not state whether the code
  includes, stores, or does not change the value. Use the verb for what the code does, such as
  includes, stores, or does not change.
- leave, leaves, leaving: "a size check leaves the path out of the line count" does not state
  whether the check excludes, removes, or does not change the path. Use the verb for what the code
  does, such as excludes, does not count, does not set, or does not read.
- skip, skips, skipped, skipping: "the hook skips the tests" does not state whether the hook
  excludes, does not read, or does not run the tests. Use the verb for what the code does, such as
  excludes, does not read, or does not run.
- whose: "a repository whose database check fails" hangs a clause about a second noun on the first
  noun. State the fact with a plain phrase or a separate sentence, such as "a repository with a
  failing database check".

## Vague phrases

A vague phrase states a benefit and does not state how the code delivers the benefit. Replace the
phrase with the mechanism.

| Before                                          | After                                                                                |
| ----------------------------------------------- | ------------------------------------------------------------------------------------ |
| The update bar never gets in the way.           | The update bar appears only while a new service worker version is waiting.           |
| The update never interrupts a half-filled form. | The new service worker version activates only after the user clicks Reload.          |
| The env check protects secrets.                 | The pre-commit hook rejects a staged file that contains a value from a `.env` file.  |
| The `pr` script makes opening a PR smoother.    | The `pr` script runs `npm run check:all` and opens the PR only if every step passes. |

## Adjective endings

Do not end a sentence, a test title, or a `describe` title in an adjective, such as missing, blank,
deep, unset, offline, or open. An adjective ending describes a state without the action that causes
the state. Put the adjective before a noun, or state the action with a verb. A passive verb for an
event, such as "when a file is deleted", is not an adjective ending.

| Before                                 | After                         |
| -------------------------------------- | ----------------------------- |
| reports the port as free               | reports a free port           |
| when the database settings are missing | without the database settings |
| when the web app folder is blank       | with a blank web app folder   |

## Verb plus no

Do not put "no" between a verb and a noun, such as "sets no web app folder" or "has no session
cookie". Write "does not" with the verb, and "a" or "any" before the noun.

| Before                                 | After                                           |
| -------------------------------------- | ----------------------------------------------- |
| sets no web app folder                 | does not set a web app folder                   |
| when the request has no session cookie | when the request does not have a session cookie |
| finds no user for an unknown id        | does not find a user for an unknown id          |

## Grammar

Keep each sentence under 30 words, with at most one clause joined by a comma and "which", "so",
"and", or "but". A count does not show whether a reader has to reparse a sentence. Read each
sentence for the patterns below.

### Dropped "that"

A relative clause without "that" reads as a second noun phrase until the verb arrives. Add "that"
before the clause.

| Before                           | After                                 |
| -------------------------------- | ------------------------------------- |
| a row with an id the client made | a row with an id that the client sets |
| Port the server listens on       | Port that the server listens on       |

### Stacked clause

A noun followed by a phrase with a second noun inside makes the reader hold two nouns at once. Use a
shorter noun phrase, or move the second fact into a verb.

| Before                                            | After                       |
| ------------------------------------------------- | --------------------------- |
| a symlink with a space in the symlink name        | a symlink path with a space |
| functions with bodies that span few lines of code | short functions             |

### Joined clauses

A sentence that chains clauses with commas, "which", or "so" states several facts at once. Write
each fact as a separate sentence, even when the joined version is short.

```text
Before: The script reads the port from the config, which defaults to 3000, then exits when the port is taken.
After:  The script reads the port from the config. The port defaults to 3000. The script exits when the port is taken.
```

### Comments with three or more sentences

A comment with three or more sentences mixes the facts together. Write a lead-in line, then one fact
per bullet.

```text
Before:
# Folder holding the built web app, relative to apps/server, for example ../web/dist.
# Set it only in a hosted build, where this server also serves the web app. Keep it
# blank locally.

After:
# Folder that contains the built web app, relative to apps/server, such as ../web/dist:
# - Set the folder only in a hosted build, where the server also serves the web app
# - Keep the folder blank locally
```

### Awkward wraps

A sentence that starts near the end of a comment line and wraps after a few words splits one fact
across two lines. Start each sentence on a new comment line.

```text
Before:
# Defaults to info. Use
# debug to read each request.

After:
# Defaults to info.
# Use debug to read each request.
```

## Docs for a reader

A doc, such as a README, has to make sense to a contributor on the first day. The grammar rules do
not catch a doc that reads like a list of labels.

### Supporting facts as nested bullets

Put a fact that supports a list item in a nested bullet under the item. Do not add the fact as an
extra sentence after the item.

```text
Before:
4. Read the safe values from `.safe-commit-values`. Each line is one value. The check excludes blank lines.

After:
4. Read the safe values from `.safe-commit-values`.
   - Each line of the file is one safe value.
   - The check ignores blank lines.
```

### Instructions instead of fragments

Write each list item as an instruction or a full fact. A noun phrase without a verb does not tell
the reader what to do.

| Before                                 | After                                                                               |
| -------------------------------------- | ----------------------------------------------------------------------------------- |
| Tailscale on the Mac and on the phone  | Install Tailscale on the Mac and on the phone. Sign in to the same account on both. |
| The scores for the lane:               | `resume_score.py` writes the lane score to `resume-score.json`.                     |

### Facts from the code

Read the code behind each statement before writing the statement, such as the package script, the
example settings file, or the route. A doc that describes a default port or a printed message
differently from the code sends the reader down the wrong path.

### Proofread as a reader

After writing a doc, launch a proofreader subagent. Ask the subagent to read the doc as real English
for a first-day contributor and to check each statement against the code. Do not give the subagent
the intended meaning of the doc. Fix each problem that the subagent reports.

## Numbered steps

Write the numbered steps of a skill or a ticket plan with the skill-writing skill.

## Reread the text

After writing, reread the text once for each problem below, and rewrite each sentence with the
problem:

1. A pronoun from the list above without a noun
2. A word from the "Forbidden words" list
3. A claim that states a benefit instead of the mechanism
4. A sentence or a title that ends in an adjective
5. A verb followed by "no" and a noun
6. A relative clause without "that"
7. A noun with a stacked clause
8. A sentence that chains clauses with commas, "which", or "so"
9. A comment with three or more sentences, instead of a lead-in line and bullets
10. A sentence that wraps after a few words
11. A supporting fact added as an extra sentence instead of a nested bullet
12. A list item that is a noun fragment instead of an instruction or a full fact
