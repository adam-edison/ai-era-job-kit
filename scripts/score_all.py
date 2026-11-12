#!/usr/bin/env python3
"""The whole scoring chain in one command: steps 1 to 6.

  cd ~/job-search          # your work folder, outside any git repository
  python3 score_all.py --resume my-resume.pdf --role "software developer" \\
      [--linkedin Profile.pdf] [--github yourhandle --repos repo-a,owner/repo-b] [--url https://yourname.dev]

  python3 score_all.py     # every run after that: it remembers what you gave it

  --allow-repo lets the work folder sit inside a private git repository; it is remembered too.

It runs the same scripts you would run by hand, in order, and writes every report into the folder:
  1. resume_score.py     resume-score.json / .md
  2. linkedin_score.py   linkedin-score.json / .md     (with --linkedin)
  3. github_score.py     github-score.json / .md       (with --github)
  4. portfolio_audit.py  portfolio-score.json / .md    (with --url; adds checklist.json if the folder has one)
  5. scorecard.py composite   composite.json / .md
  6. scorecard.py plan        plan.md
Then it prints the combined report. Leave a surface out and the chain runs without it; the report says the
scores are partial. Your answers are saved to score-all.json in the folder, so the next run needs no flags.
A flag you pass again replaces the saved one.

Nothing is guessed. If a surface can't be scored this run (a live pull failed, a file is missing), it is
left out of the combined report and named at the end, and the run exits 3. An older score file is never
used in its place. A resume that can't be scored stops the run: every other step reads the lane from it.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import github_score  # noqa: E402
import linkedin_score  # noqa: E402
import portfolio_audit  # noqa: E402
import resume_score  # noqa: E402
import scorecard  # noqa: E402
import screen_grade as sg  # noqa: E402

SAVED = "score-all.json"
KEYS = ("resume", "role", "onet", "postings", "linkedin", "github", "repos", "url", "portfolio", "checklist", "allow_repo")
NAME = {"resume": "Resume", "linkedin": "LinkedIn", "github": "GitHub", "portfolio": "Portfolio"}


def quiet(fn, argv: list[str]) -> tuple[int, str]:
    """Run one step's main() and hold its report back: the run prints one line per step, then the combined report."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fn(argv)
    return code, buf.getvalue()


def settings(a: argparse.Namespace, folder: pathlib.Path) -> dict:
    saved = folder / SAVED
    s = json.loads(saved.read_text()) if saved.exists() else {}
    given = {k: getattr(a, k) for k in KEYS if getattr(a, k)}
    if "role" in given or "onet" in given:  # a new lane replaces the saved one, whichever way it was named
        s.pop("role", None), s.pop("onet", None)
    s.update(given)
    if "checklist" not in s and (folder / "checklist.json").exists():
        s["checklist"] = "checklist.json"
    return s


def run(s: dict, folder: pathlib.Path) -> int:
    out = lambda name: str(folder / name)
    at = lambda p: str((folder / pathlib.Path(p).expanduser()))  # saved paths are relative to the folder
    opt = lambda flag, key: [flag, at(s[key])] if s.get(key) else []
    scored: dict[str, str] = {}
    failed: list[str] = []

    def line(surface: str, path: str) -> None:
        scored[surface] = path

    lane = ["--onet", s["onet"]] if s.get("onet") else ["--role", s["role"]]
    allow = ["--allow-repo"] if s.get("allow_repo") else []
    code, text = quiet(resume_score.main, ["--resume", at(s["resume"]), *lane, *opt("--postings", "postings"), *allow,
                                           "--json", out("resume-score.json"), "--md", out("resume-score.md")])
    if code == 1:  # read, but no score: the parse gate. The report says what to fix.
        print(text)
        print("Stopped at step 1: the resume has no score yet. Fix the format above and run this again.", file=sys.stderr)
        return 1
    if code:
        return code
    line("resume", out("resume-score.json"))
    market = ["--market", out("resume-score.json"), *opt("--portfolio", "portfolio")]

    if s.get("linkedin"):
        code, _ = quiet(linkedin_score.main, ["--profile", at(s["linkedin"]), *market, "--resume", at(s["resume"]),
                                              "--json", out("linkedin-score.json"), "--md", out("linkedin-score.md")])
        failed.append("LinkedIn") if code else line("linkedin", out("linkedin-score.json"))
    if s.get("github"):
        code, _ = quiet(github_score.main, ["--user", s["github"], *(["--repos", s["repos"]] if s.get("repos") else []),
                                            *market, "--json", out("github-score.json"), "--md", out("github-score.md")])
        failed.append("GitHub") if code else line("github", out("github-score.json"))
    if s.get("url"):
        code, text = quiet(portfolio_audit.main, ["--url", s["url"], *opt("--portfolio", "portfolio"),
                                                  *opt("--checklist", "checklist"), "--json", out("portfolio-score.json")])
        if code:
            failed.append("Portfolio")
        else:
            pathlib.Path(out("portfolio-score.md")).write_text(text)
            line("portfolio", out("portfolio-score.json"))

    # the resume report now counts what GitHub and LinkedIn showed, so it carries the number the combined report uses
    load = lambda k: json.loads(pathlib.Path(scored[k]).read_text())
    res = resume_score.corroborate(load("resume"), resume_score.merge_evidence(
        *[load(k) for k in ("linkedin", "github") if k in scored]))
    pathlib.Path(out("resume-score.json")).write_text(json.dumps(res, indent=2))
    pathlib.Path(out("resume-score.md")).write_text(resume_score.report_md(res))
    for k, p in scored.items():
        print(f"  {NAME[k]:<10}{load(k)['score']:>4} / 100   {pathlib.Path(p).with_suffix('.md').name}")
    args = [x for k, p in scored.items() for x in (f"--{k}", p)]
    code, text = quiet(scorecard.main, ["composite", *args, "--json", out("composite.json"), "--md", out("composite.md")])
    if code:
        return code
    quiet(scorecard.main, ["plan", "--composite", out("composite.json"), "--md", out("plan.md")])
    print()
    print(text)
    print(f"What to fix first: {out('plan.md')}")
    if failed:
        print(f"Not scored this run, so left out above: {', '.join(failed)}. The reason is printed above. "
              "Fix it and run this again.", file=sys.stderr)
        return 3
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=".", help="your work folder, outside any git repository (default: this folder)")
    ap.add_argument("--resume", help="your resume: .pdf, .docx or .txt")
    ap.add_argument("--role", help='the job you want, e.g. "software developer"')
    ap.add_argument("--onet", help="or the O*NET code, e.g. 15-1252.00")
    ap.add_argument("--postings", help="a folder of saved postings for the lane")
    ap.add_argument("--linkedin", help="your profile as .txt, or LinkedIn's Save to PDF file")
    ap.add_argument("--github", help="your GitHub handle")
    ap.add_argument("--repos", help="your pinned repos, comma-separated; owner/repo for a pin under an organization")
    ap.add_argument("--url", help="your portfolio site")
    ap.add_argument("--portfolio", help="portfolio.json, the master record")
    ap.add_argument("--checklist", help="the portfolio judgment pass (the portfolio-scorer skill writes it)")
    ap.add_argument("--allow-repo", action="store_true",
                    help="allow a work folder inside a private git repository (remembered for later runs)")
    a = ap.parse_args(argv)
    folder = pathlib.Path(a.dir).expanduser().resolve()
    if not folder.is_dir():
        print(f"REFUSED: folder not found: {folder}", file=sys.stderr)
        return 2
    try:
        s = settings(a, folder)
    except ValueError as e:
        print(f"REFUSED: {folder / SAVED} isn't valid JSON ({e}). Delete it and pass the flags again.", file=sys.stderr)
        return 2
    if not s.get("allow_repo") and sg.in_git_repo(folder / SAVED):
        print("REFUSED: keep resumes and their scores outside any git repository. "
              "Run this from a work folder such as ~/job-search, or pass --allow-repo if the repository is private.",
              file=sys.stderr)
        return 2
    if not s.get("resume") or not (s.get("role") or s.get("onet")):
        print('REFUSED: the first run needs --resume and --role (or --onet), e.g.\n'
              '  python3 score_all.py --resume my-resume.pdf --role "software developer"', file=sys.stderr)
        return 2
    (folder / SAVED).write_text(json.dumps(s, indent=2))
    print(f"Scoring from {folder}")
    return run(s, folder)


if __name__ == "__main__":
    sys.exit(main())
