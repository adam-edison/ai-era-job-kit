#!/usr/bin/env python3
"""Resume score: step 1 of the scoring chain.

How well one resume proves what the market for one lane asks for, after the parse gate.
Every rule here traces to references/ats-research.md.

  python3 resume_score.py --resume resume.pdf --onet 15-1252.00 [--postings ./postings] \\
      [--boards greenhouse:stripe ...] [--json resume-score.json] [--md resume-score.md]

What it does, in the ATS's own order:
  1. Parse gate. Extract the text; if it can't be read (too few words, no standard headings, no dates,
     side-by-side columns), the result is "no score, fix the format". A missing email or phone is a
     fix on the report, not a block: the file still parses.
     [vendor: HiredScore gives no grade to unreadable files; parse-breakers from Jerome's Feb 3 and Feb 4 chats]
  2. Pull the lane live: O*NET Technology Skills for the occupation, plus your saved postings or public
     boards if you give them, and the BLS 10-year outlook. If a pull fails, it stops. It never guesses.
  3. Grade each in-demand skill on its evidence across the resume, GitHub and LinkedIn:
       proven 1.0  named in an Experience or Projects line that has a number, AND the same skill shows in
                   recent public work: a pinned repo pushed in the last year (step 3), or LinkedIn
                   Experience, Projects or Featured (step 2)
       applied 0.7 named in an Experience or Projects line, but missing the number or the outside proof
       listed 0.4  named only in Skills or the summary
       stale 0.3   proven or applied only in roles that ended 5+ years ago, counted to the month
       none 0
     [Evidence over lists, Sept 17 2026; signal strength, Feb 3 2026; recency, Jan 11 2026; rankers read
      LinkedIn and GitHub alongside the resume, Oct 7 and Sept 17 2026; AI screeners score GitHub and
      LinkedIn activity against the posting, Jerome Nov 8 2026 (chat only)]
     Pass --github and --linkedin (the step 2 and 3 JSON) to back skills here. Without them no skill can
     reach proven yet; the composite (step 5) applies the same rule from the step 2 and 3 files.
     "A number" is a quantity (40%, 10,000, $2M, 3x), not a digit inside a name (S3, EC2, OAuth2).
     "Backed" is corroboration you supply, not verification: the script checks the skill shows up there.
  4. Score = your best --need skills (default 10), demand-weighted, x 100. No one resume proves every
     skill a whole occupation uses, so the score asks for the lane's most-wanted ten, not all of them:
     100 means the ten highest-demand skills are all proven. [VWC design judgment, configurable]
     The JSON also carries text_score: the same sum from the resume alone, before outside proof.
     Both include the kit's 10-point calibration, capped at 100 (jobdata/calibration.py).
     Lift = points gained if that skill were proven.
  5. Flags, reported and not scored: chronology (gaps over 6 months, roles under a year), old keyword
     tricks, and Harvard Extension School format rules.

The per-posting Screen Grade (A to D) is screen_grade.py. Run this on the resume you send for the lane,
that one per posting.

Exit codes: 0 scored, 1 no score (parse gate failed), 2 bad input, 3 a live pull failed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from jobdata import bls as bls_mod  # noqa: E402
from jobdata import calibration as cal  # noqa: E402
from jobdata import demand as dm  # noqa: E402
from jobdata import docs, lexicon  # noqa: E402
from jobdata import onet as onet_mod  # noqa: E402
from jobdata import postings as post_mod  # noqa: E402
from jobdata.net import FetchError  # noqa: E402
import screen_grade as sg  # noqa: E402

GRADES = {"proven": 1.0, "applied": 0.7, "listed": 0.4, "stale": 0.3, "none": 0.0}
ACTIVE_DAYS = 365  # "recent public work": a pinned repo pushed within a year. VWC design judgment, configurable.
NEED = 10  # skills the score asks a resume to prove. VWC design judgment, configurable with --need.
YEAR = re.compile(r"(19|20)\d{2}")
BAD_CHARS = re.compile(r"[→←⇒➔➜~★✓✔◆■□▶►]")


def as_years(now) -> float:
    """A date as a fractional year. A bare year means the end of that year."""
    if isinstance(now, dt.date):
        return now.year + now.month / 12
    return float(now) + 1.0


def role_spans(lines: list[tuple[str, str]], now) -> list[tuple[float, float]]:
    """For each resume line, the (start, end) of the role it sits under in fractional years, or (0, 0)."""
    cur = (0, 0)
    out = []
    for sec, line in lines:
        m = sg.DATE_RANGE.search(line)
        if m and sec in sg.EXP_SECTIONS:
            a = YEAR.search(m.group(1))
            b = YEAR.search(m.group(2))
            end = int(b.group(0)) + _month(m.group(2), default=12) / 12 if b else as_years(now)
            cur = (int(a.group(0)) if a else 0, end)
        elif sec not in sg.EXP_SECTIONS:
            cur = (0, 0)
        out.append(cur)
    return out


def grade_skill(skill: str, vocab: dict, lines: list[tuple[str, str]], spans, now) -> tuple[str, str]:
    pats = [lexicon._pattern(a) for a in vocab.get(skill, [skill.lower()])]
    best_recent, best_old, listed, quote = None, None, False, ""
    for (sec, line), (_, end) in zip(lines, spans):
        if not any(p.search(line) for p in pats):
            continue
        if sec in sg.EXP_SECTIONS:
            g = "proven" if lexicon.has_number(sg.DATE_RANGE.sub("", line)) else "applied"
            old = end and end <= as_years(now) - 5
            slot = "old" if old else "recent"
            if slot == "recent" and (best_recent is None or GRADES[g] > GRADES[best_recent]):
                best_recent, quote = g, line
            if slot == "old" and (best_old is None or GRADES[g] > GRADES[best_old]):
                best_old = g
                quote = quote or line
        else:
            listed = True
            quote = quote or line
    if best_recent:
        return best_recent, quote
    if best_old:
        return "stale", quote
    if listed:
        return "listed", quote
    return "none", ""


def chronology(text: str, now: int) -> list[dict]:
    """Gaps over 6 months and roles under a year: things a screener may flag for review (Jan 11 2026)."""
    spans = []
    for m in sg.DATE_RANGE.finditer(text):
        a, b = YEAR.search(m.group(1)), YEAR.search(m.group(2))
        if not a:
            continue
        mon_a = _month(m.group(1))
        sa = int(a.group(0)) + (mon_a - 1) / 12
        if b:
            eb = int(b.group(0)) + (_month(m.group(2), default=12) - 1) / 12
        else:
            eb = now + (dt.date.today().month - 1) / 12
        spans.append((sa, eb, m.group(0)))
    flags = []
    for sa, eb, label in spans:
        if 0 <= eb - sa < 1 and _month_given(label):
            flags.append({"flag": "Role under a year", "detail": label,
                          "fix": "Be ready to explain it in one line (contract, layoff, move). Group contract roles under one heading if true."})
    ordered = sorted(spans)
    for i in range(1, len(ordered)):  # a gap is time no role covers: a long role running alongside fills it
        e1, l1 = max((e, l) for _, e, l in ordered[:i])
        s2, _, l2 = ordered[i]
        if s2 - e1 > 0.5:
            flags.append({"flag": "Gap over 6 months", "detail": f"{l1} then {l2}",
                          "fix": "Fill it with what's true: training, a build, volunteer work, caregiving, service."})
    return flags


MONTH_NAMES = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def _month(s: str, default: int = 1) -> int:
    m = re.match(r"\s*([a-z]{3})", s.lower())
    return MONTH_NAMES.index(m.group(1)) + 1 if m and m.group(1) in MONTH_NAMES else default


def _month_given(label: str) -> bool:
    return len(re.findall(r"\b(?:" + "|".join(MONTH_NAMES) + r")", label.lower())) >= 2


def parse_breakers(text: str, lines: list[tuple[str, str]]) -> list[dict]:
    """Extra parse checks from Jerome's chats (Feb 3 and Feb 4 2026). Chat-only rules are labeled."""
    top = "\n".join(text.splitlines()[:6])
    odd = sorted(set(BAD_CHARS.findall(text)))
    odd_heads = [l for s, l in lines if s == "header" and re.fullmatch(r"[A-Z][A-Za-z &/]{3,40}", l)
                 and re.search(r"selected|thought leadership|highlights|about me|my ", l, re.I)]
    return [
        {"check": "Contact info in the top lines", "ok": bool(sg.EMAIL.search(top)), "source": "Feb 3 2026: headers and footers are often skipped",
         "fix": "Put email and phone as plain text in the first lines of the body, not in a header or footer."},
        {"check": "No special characters parsers choke on", "ok": not odd, "detail": " ".join(odd), "source": "Feb 4 2026 (chat only)",
         "fix": "Replace arrows, tildes and decorative symbols with words or plain hyphens; use pipes in the contact line."},
        {"check": "Standard section names", "ok": not odd_heads, "detail": "; ".join(odd_heads[:3]), "source": "Feb 3 and Feb 4 2026",
         "fix": "Rename to Experience, Projects, Skills, Education."},
    ]


def score(text: str, onet_rows: list[dict], posts: list[dict], now=None, top: int = 25,
          outside: dict[str, list[str]] | None = None, need: int = NEED) -> dict:
    """now: a date, or a bare year (read as the end of that year). Defaults to today."""
    now = now or dt.date.today()
    year = now.year if isinstance(now, dt.date) else int(now)
    lines = sg.sections(text)
    gate = sg.parse_gate(text, lines)
    breakers = parse_breakers(text, lines)
    demand, vocab = dm.build_demand(onet_rows, posts, top=top)
    out = {"surface": "resume", "parse_gate": gate, "parse_breakers": breakers, "need": need,
           "postings": len(posts), "basis": "postings, O*NET breaks ties" if posts else "O*NET flags only (no postings given)"}
    if not sg.readable(gate):
        out.update(score=None, verdict="No score: fix the format first. A screener that can't parse the file gives no grade.")
        return out
    spans = role_spans(lines, now)
    skills = []
    for d in demand:
        g, q = grade_skill(d.skill, vocab, lines, spans, now)
        skills.append({"skill": d.skill, "weight": d.weight, "posting_share": d.posting_share,
                       "onet_hot": d.onet_hot, "onet_in_demand": d.onet_in_demand, "text_grade": g, "evidence": q[:160]})
    fmt = sg.format_checks(text, lines)
    base = ([{"section": "Parse", "check": g["check"], "pass": False, "detail": g["detail"], "weight": 2, "fix": g["fix"]}
             for g in gate if not g["ok"]]  # email or phone missing: a fix, not a block
            + [{"section": "Parse", "check": b["check"], "pass": b["ok"], "detail": b.get("detail", ""), "weight": 2, "fix": "" if b["ok"] else b["fix"]} for b in breakers]
            + [{"section": "Format (HES/VWC)", "check": f["rule"], "pass": f["ok"], "detail": "; ".join(f["examples"])[:160], "weight": 1,
                "fix": "" if f["ok"] else f"Fix: {f['rule']}."} for f in fmt])
    out.update(skills=skills, checks=base, format=fmt, chronology=chronology(text, year),
               manipulation=sg.manipulation_flags(text, lines, vocab))
    return corroborate(out, outside)


def merge_evidence(*surfaces: dict | None) -> dict[str, list[str]]:
    """Join the skill_evidence maps from the LinkedIn and GitHub scores: {skill: [where it shows]}."""
    out: dict[str, list[str]] = {}
    for s in surfaces:
        for k, v in ((s or {}).get("skill_evidence") or {}).items():
            out.setdefault(k, [])
            out[k] += [x for x in v if x not in out[k]]
    return out


def best_n(pairs: list[tuple[float, float]], need: int | None) -> float:
    """Score 0-100 from (weight, grade value) pairs: the best `need` skills over the `need` biggest weights."""
    n = min(need or len(pairs), len(pairs))
    tot = sum(sorted((w for w, _ in pairs), reverse=True)[:n])
    return 100 * sum(sorted((w * g for w, g in pairs), reverse=True)[:n]) / tot if tot else 0.0


def corroborate(r: dict, outside: dict[str, list[str]] | None = None) -> dict:
    """Final grades: a resume bullet with a number is proven only when GitHub or LinkedIn backs the same skill."""
    if r.get("score") is None and not r.get("skills"):
        return r
    outside = outside or {}
    seen = {k.lower(): v for k, v in outside.items()}
    need = r.get("need")  # files written before --need existed score every skill, as they did then
    for k in r["skills"]:
        tg = k.get("text_grade", k.get("grade", "none"))
        k["text_grade"] = tg
        k["backed_by"] = seen.get(k["skill"].lower(), [])
        k["grade"] = "proven" if tg == "proven" and k["backed_by"] else ("applied" if tg == "proven" else tg)
    pairs = [(k["weight"], GRADES[k["grade"]]) for k in r["skills"]]
    now_score = best_n(pairs, need)
    for i, k in enumerate(r["skills"]):  # lift: the score with this one skill proven, minus the score now
        k["lift"] = round(best_n(pairs[:i] + [(k["weight"], 1.0)] + pairs[i + 1:], need) - now_score, 1)

    def fix(k):
        need = []
        if k["text_grade"] != "proven":
            need.append("name it in a recent Experience or Projects bullet with a number")
        if not k["backed_by"]:
            need.append("show it in a pinned repo pushed this year or in LinkedIn Experience")
        return f"{k['skill']}: " + ", and ".join(need) + f" (+{k['lift']} points)."

    base = [c for c in r.get("checks", []) if c["section"] != "Evidence"]
    ev = [{"section": "Evidence", "check": f"Prove {k['skill']}", "pass": k["grade"] == "proven",
           "detail": f"now {k['grade']}" + (f"; backed by {', '.join(k['backed_by'])}" if k["backed_by"] else ""),
           "weight": k["lift"], "fix": fix(k)}
          for k in sorted(r["skills"], key=lambda x: (-x["lift"], -GRADES[x["grade"]])) if k["lift"] > 0]  # ties: what's already on the resume first
    r.update(score=cal.calibrate(now_score), checks=base + ev, corroborated=bool(outside), calibration=cal.CALIBRATION,
             text_score=cal.calibrate(best_n([(k["weight"], GRADES[k["text_grade"]]) for k in r["skills"]], need)))
    return r


def report_md(r: dict) -> str:
    L = ["# Resume score (step 1 of the chain)", ""]
    if r.get("score") is None:
        L += [f"**{r['verdict']}**", "", "| Parse check | OK | Fix |", "|---|---|---|"]
        L += [f"| {g['check']} | {'yes' if g['ok'] else 'no'} | {g['fix']} |" for g in r["parse_gate"]]
        return "\n".join(L)
    o = r.get("outlook") or {}
    L += [f"**{r['score']} / 100** for {r.get('title', r.get('onet_code', 'this lane'))}. Basis: {r['basis']}, {r['postings']} postings.", ""]
    if r.get("need"):
        L += [f"The score counts your best {min(r['need'], len(r['skills']))} of the lane's {len(r['skills'])} in-demand skills, "
              f"weighted by demand (--need). From the resume alone, before outside proof: {r.get('text_score')} / 100.", ""]
    if o:
        L += [f"BLS outlook (live): {o.get('growth_pct_10yr')}% 10-year growth, {o.get('annual_openings_thousands')}k openings a year.", ""]
    if not r.get("corroborated"):
        L += ["No GitHub or LinkedIn evidence given, so no skill is proven yet. Proven needs the resume bullet with a number",
              "and the same skill in recent GitHub work or on LinkedIn. Run steps 2 and 3, then the composite (or rerun with --github and --linkedin).", ""]
    L += ["| Skill | Grade | Lift | Resume evidence | Backed by |", "|---|---|---|---|---|"]
    for k in sorted(r["skills"], key=lambda x: (-x["lift"], -GRADES[x["grade"]], x["skill"])):
        L.append(f"| {k['skill']} | {k['grade']} | {k['lift']} | {k['evidence'][:80]} | {', '.join(k.get('backed_by') or [])} |")
    bad = [c for c in r["checks"] if not c["pass"] and c["section"] != "Evidence"]
    if bad:
        L += ["", "## Format and parse fixes", *[f"- {c['fix']}" for c in bad]]
    if r["chronology"]:
        L += ["", "## Be ready to explain (flagged, not scored)", *[f"- {c['flag']}: {c['detail']}. {c['fix']}" for c in r["chronology"]]]
    if r["manipulation"]:
        L += ["", "## Remove these", *[f"- {m['flag']} {m['line']}".rstrip() for m in r["manipulation"]]]
    L += ["", cal.NOTE, "", "Next: score LinkedIn, GitHub and the portfolio, then run the composite. It confirms proven skills from them."]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resume", required=True)
    ap.add_argument("--onet", help="O*NET-SOC code for the lane, e.g. 15-1252.00")
    ap.add_argument("--role", help="search O*NET by role name instead of --onet")
    ap.add_argument("--postings")
    ap.add_argument("--boards", nargs="*", default=[])
    ap.add_argument("--role-filter")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--need", type=int, default=NEED, help=f"how many lane skills the score asks you to prove (default {NEED})")
    ap.add_argument("--github", help="github-score.json from step 3: skills shown in recent pinned repos")
    ap.add_argument("--linkedin", help="linkedin-score.json from step 2: skills shown in Experience, Projects, Featured")
    ap.add_argument("--json")
    ap.add_argument("--md")
    ap.add_argument("--allow-repo", action="store_true", help="allow the resume and reports inside a private git repository")
    a = ap.parse_args(argv)
    if a.need < 1:
        ap.error("--need must be 1 or more")
    if not (a.onet or a.role):
        ap.error("give --onet or --role")
    if not a.allow_repo and any(sg.in_git_repo(pathlib.Path(x).expanduser().resolve()) for x in (a.resume, a.json, a.md) if x):
        print("REFUSED: keep resumes and their scores outside any git repository, "
              "or pass --allow-repo if the repository is private.", file=sys.stderr)
        return 2
    try:
        text = docs.read_text(a.resume)
        outside = merge_evidence(*[json.loads(pathlib.Path(x).expanduser().read_text()) for x in (a.github, a.linkedin) if x])
        if a.postings and not pathlib.Path(a.postings).expanduser().is_dir():
            raise FileNotFoundError(f"Postings folder not found: {a.postings}")
    except (OSError, ValueError, RuntimeError) as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    try:
        on = onet_mod.Onet()
        code = a.onet
        if not code and a.role:
            hit = on.search(a.role, limit=1)
            code = hit[0]["code"] if hit else None
        if not code:
            print(f"REFUSED: no O*NET occupation matches \"{a.role}\". Look the code up at https://www.onetonline.org/find/ and pass --onet.", file=sys.stderr)
            return 2
        rows = on.technology_skills(code)
        posts, warn = post_mod.gather(a.postings, a.boards, a.role_filter)
        r = score(text, rows, posts, top=a.top, outside=outside, need=a.need)
        r.update(onet_code=code, title=on.title(code), onet_release=on.version, warnings=warn)
        o = bls_mod.Bls().projections(code)
        r["outlook"] = {"growth_pct_10yr": o.get("growth_pct_10yr"),
                        "annual_openings_thousands": o.get("annual_openings_thousands"), "source": o.get("source")}
    except FetchError as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        return 3
    md = report_md(r)
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(r, indent=2))
    if a.md:
        pathlib.Path(a.md).write_text(md)
    print(md)
    return 0 if r.get("score") is not None else 1


if __name__ == "__main__":
    sys.exit(main())
