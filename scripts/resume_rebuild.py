#!/usr/bin/env python3
"""Resume rebuilder: step 7 of the scoring chain. Rebuilds your resume to the VWC spec from your portfolio.

  # Draft a targeted resume from the master record, ordered by the resume score's lift list
  python3 resume_rebuild.py --portfolio <repo>/portfolio.json --brag <repo>/brag/entries \\
      --market resume-score.json [--role "Backend Engineer"] --out ~/resumes/you-backend-resume.txt

  # Lint any resume against the spec (parse gate, parse breakers, HES/VWC format)
  python3 resume_rebuild.py --check ~/resumes/you-backend-resume.pdf

The portfolio is the single source of truth, so the draft only uses what portfolio.json and your curated
brag entries say. It never invents employers, titles, dates, numbers or skills: anything missing comes out
as [ask: ...] for you to fill in. A lane skill with no evidence in the portfolio is listed in the report as
"prove it first", never added to the resume.

The spec (resume-rebuilder skill): single column; standard headings Experience, Projects, Skills, Education;
email and phone as plain text in the top lines; no pronouns, no "Responsible for", no line that starts with a
date; reverse chronological; no references; experience length as 5+ or 10+ only. Bullets: strong verb, what
you built or changed, the skill named the market's way, and a number. [HES, VWC]

Resumes stay out of git: --out refuses a path inside a git repository, the portfolio repo included.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import screen_grade as sg  # noqa: E402
from jobdata import docs, lexicon  # noqa: E402
from resume_score import parse_breakers  # noqa: E402

MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def nice_date(d: str) -> str:
    d = (d or "").strip()
    if d.lower() in ("present", "current", "now", ""):
        return "Present" if d else "[ask: date]"
    m = re.fullmatch(r"((?:19|20)\d{2})-(\d{2})", d)
    return f"{MONTH[int(m.group(2)) - 1]} {m.group(1)}" if m else d


def read_brag(folder: str | None) -> list[dict]:
    """Curated brag entries: one item per '### accomplishment' heading."""
    out: list[dict] = []
    if not folder:
        return out
    for f in sorted(pathlib.Path(folder).expanduser().glob("*.md")):
        text = f.read_text(errors="replace")
        if re.search(r"^status:\s*raw", text, re.M):
            continue  # only curated entries feed the resume
        area, cur = "", None
        for line in text.splitlines():
            if line.startswith("## "):
                area = line[3:].strip()
            elif line.startswith("### "):
                cur = {"file": f.name, "anchor": slug(line[4:]), "area": area, "what": line[4:].strip(),
                       "impact": "", "skills": [], "artifact": ""}
                out.append(cur)
            elif cur is not None:
                m = re.match(r"^\s*-\s*(Impact|Skills|Portfolio artifact):\s*(.*)$", line, re.I)
                if m:
                    k, v = m.group(1).lower(), m.group(2).strip()
                    if k == "impact":
                        cur["impact"] = v
                    elif k == "skills":
                        cur["skills"] = [x.strip() for x in re.split(r"[,;]", v) if x.strip()]
                    else:
                        cur["artifact"] = v
    return out


def bullet(item: dict) -> str:
    what = item["what"].rstrip(".")
    imp = item["impact"].strip()
    if not imp or imp.startswith(("<", "_(")):
        imp = "[ask: impact, with a number]"
    elif not re.search(r"\d", imp) and "[ask" not in imp:
        imp += " [ask: a number]"
    return f"- {what}: {imp.rstrip('.')}"


def load_market(path: str | None) -> tuple[list[dict], dict]:
    if not path:
        return [], {}
    r = json.loads(pathlib.Path(path).read_text())
    skills = r.get("skills") or []
    vocab = lexicon.build_vocab([s["skill"] for s in skills if s["skill"] not in lexicon.CURATED])
    return skills, vocab


def rebuild(record: dict, brag: list[dict], market: list[dict], vocab: dict, role: str | None = None) -> dict:
    prof = record.get("profile", {})
    links = record.get("links", {})
    role = role or prof.get("target_role") or "[ask: target role]"
    weight = {s["skill"]: s.get("weight", 0) for s in market}
    lift = {s["skill"]: s.get("lift", 0) for s in market}

    def rank(text: str) -> float:  # bullets that prove high-lift lane skills go first
        found = lexicon.find_skills(text, vocab) if vocab else set()
        return -sum(lift.get(s, 0) + weight.get(s, 0) for s in found)

    by_ref = {f"{b['file']}#{b['anchor']}": b for b in brag}
    used: set[int] = set()
    L = [prof.get("name") or "[ask: name]"]
    contact = [prof.get("location") or "[ask: city, state]", prof.get("email") or "[ask: email]",
               prof.get("phone") or "[ask: phone]"] + [links[k] for k in ("site", "linkedin", "github") if links.get(k)]
    head = prof.get("headline") or "[ask: one-line headline]"
    L += [" | ".join(contact), "", head if role.lower() in head.lower() else f"{role} · {head}"]

    exp = sorted(record.get("experience", []), key=lambda e: e.get("start", ""), reverse=True)
    if exp:
        L += ["", "EXPERIENCE"]
    for e in exp:
        L.append(f"{e.get('title') or '[ask: title]'}, {e.get('org') or '[ask: org]'}, {nice_date(e.get('start', ''))} - {nice_date(e.get('end', 'present'))}")
        items = []
        for h in e.get("highlights", []):
            b = by_ref.get(h.split("/")[-1])
            if b:
                items.append(b)
                used.add(id(b))
        items.sort(key=lambda b: rank(" ".join([b["what"], b["impact"], *b["skills"]])))
        L += [bullet(b) for b in items] or ["- [ask: two or three results from this role, each with a number]"]

    arts = sorted(record.get("artifacts", []), key=lambda a: (-(a.get("depth") or 0), rank(" ".join(a.get("skills", [])))))
    if arts:
        L += ["", "PROJECTS"]
    for a in arts:
        L.append(f"{a.get('name') or '[ask: project name]'} | {a.get('url') or '[ask: live link or video demo]'}")
        sk = sorted(a.get("skills", []), key=lambda s: -weight.get(s, 0))
        L.append(f"- {a.get('one_liner') or '[ask: what it does, with a number]'}. Built with {', '.join(sk[:5])}")
        for b in brag:
            if id(b) not in used and b["artifact"] and slug(b["artifact"]) == slug(a.get("name", "")):
                L.append(bullet(b))
                used.add(id(b))

    proven = {s for a in record.get("artifacts", []) for s in a.get("skills", [])}
    proven |= {s for b in brag if id(b) in used for s in b["skills"]}
    skills_line = sorted(proven, key=lambda s: (-weight.get(s, 0), s.lower()))
    L += ["", "SKILLS", ", ".join(skills_line) or "[ask: skills you can prove]",
          "", "EDUCATION", record.get("education_line") or "[ask: degree or training, school, year]"]

    resume = "\n".join(L) + "\n"
    on_resume = lexicon.find_skills(resume, vocab) if vocab else set()
    gaps = [s["skill"] for s in sorted(market, key=lambda s: -s.get("lift", 0))
            if s.get("lift", 0) > 0 and s["skill"] not in on_resume][:8]
    asks = sorted(set(re.findall(r"\[ask: [^\]]+\]", resume)))
    return {"resume": resume, "role": role, "prove_first": gaps, "asks": asks,
            "unused_brag": [b["what"] for b in brag if id(b) not in used]}


def check(text: str) -> dict:
    lines = sg.sections(text)
    rows = ([{"area": "Parse gate", "check": g["check"], "ok": g["ok"], "fix": g["fix"]} for g in sg.parse_gate(text, lines)]
            + [{"area": "Parse", "check": b["check"], "ok": b["ok"], "fix": b["fix"]} for b in parse_breakers(text, lines)]
            + [{"area": "Format (HES/VWC)", "check": f["rule"], "ok": f["ok"], "fix": "; ".join(f["examples"])[:120]}
               for f in sg.format_checks(text, lines)])
    asks = re.findall(r"\[ask: [^\]]+\]", text)
    if asks:
        rows.append({"area": "Draft", "check": "No [ask: ...] left", "ok": False, "fix": f"Fill {len(asks)} placeholders."})
    return {"pass": all(r["ok"] for r in rows), "checks": rows}


def check_md(c: dict) -> str:
    L = ["# Resume spec check (step 7 of the chain)", "", "Passes the spec." if c["pass"] else "Fix these before you send it.", "",
         "| Area | Check | OK | Fix |", "|---|---|---|---|"]
    L += [f"| {r['area']} | {r['check']} | {'yes' if r['ok'] else 'no'} | {'' if r['ok'] else r['fix']} |" for r in c["checks"]]
    return "\n".join(L)


def report_md(r: dict) -> str:
    L = [f"# Rebuilt resume for {r['role']} (step 7 of the chain)", ""]
    if r["asks"]:
        L += ["Fill these in (nothing was invented):", *[f"- {a}" for a in r["asks"]], ""]
    if r["prove_first"]:
        L += ["High-lift lane skills with no evidence in your portfolio. Prove them there first; they were not added:",
              *[f"- {s}" for s in r["prove_first"]], ""]
    if r["unused_brag"]:
        L += ["Brag entries not linked to a role or artifact (link them in portfolio.json to use them):",
              *[f"- {s}" for s in r["unused_brag"][:8]], ""]
    L += ["Next: defend every line out loud, run --check, then rescore with resume_score.py and sync_check.py."]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", metavar="RESUME", help="lint a resume file against the spec and exit")
    ap.add_argument("--portfolio")
    ap.add_argument("--brag", help="brag/entries folder (curated entries)")
    ap.add_argument("--market", help="resume-score.json from step 1 (orders bullets by lift)")
    ap.add_argument("--role")
    ap.add_argument("--out", help="where to write the draft (outside any git repo)")
    ap.add_argument("--md", help="also write the report here")
    ap.add_argument("--allow-repo", action="store_true", help="allow --out inside a private git repository")
    a = ap.parse_args(argv)
    try:
        if a.check:
            c = check(docs.read_text(a.check))
            md = check_md(c)
            print(md)
            if a.md:
                pathlib.Path(a.md).write_text(md)
            return 0 if c["pass"] else 1
        if not a.portfolio:
            ap.error("give --portfolio (or --check RESUME)")
        if a.out and not a.allow_repo and sg.in_git_repo(pathlib.Path(a.out).expanduser().resolve()):
            raise ValueError(f"{a.out} is inside a git repository. Keep resumes out of git, the portfolio repo included, "
                             "or pass --allow-repo if the repository is private.")
        record = json.loads(pathlib.Path(a.portfolio).expanduser().read_text())
        market, vocab = load_market(a.market)
        r = rebuild(record, read_brag(a.brag), market, vocab, a.role)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    if a.out:
        pathlib.Path(a.out).expanduser().write_text(r["resume"])
    md = report_md(r)
    if a.md:
        pathlib.Path(a.md).write_text(md)
    print(r["resume"] if not a.out else f"Draft written to {a.out}\n")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
