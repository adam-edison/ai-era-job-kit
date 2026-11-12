#!/usr/bin/env python3
"""Screen Grade: how an AI resume screener is likely to grade one resume for one posting.

Built from what the vendors document, not from guesses (see references/ats-sources.md and references/ats-research.md):
  - Workday HiredScore grades each applicant A-D against the posting's basic and preferred
    qualifications and gives no grade to a resume in an unsupported format. Its opt-in LLM
    version (August 2026) evaluates each qualification individually and points to the evidence.
  - Greenhouse Talent Matching sorts candidates into match categories using required skills,
    relevant experience, job titles and (optionally) industry. It doesn't auto-reject.
  - NYC Local Law 144 (6 RCNY 5-300 to 5-303) makes employers audit these tools yearly and
    publish the results, measured by who scores above the median.
Each rule below is tagged [vendor] (documented by a vendor or law), [HES] (Harvard Extension
School resume guide, 2024) or [VWC] (a Vets Who Code definition). Employer weights are not public,
so this script invents none.

Two steps. A script does the counting; the grading of each qualification is done by the person
or their AI assistant, and this script refuses any grade it can't verify against the resume text.

  1. Split the posting into numbered qualifications and knockout questions:
       python3 screen_grade.py split --posting posting.txt --out quals.json
     (or --greenhouse <board> --job <id> | --lever <company> --job <id> | --ashby <board> --job <id>)
  2. Grade each qualification in grades.json (Met only with an exact resume quote), then:
       python3 screen_grade.py grade --resume resume.pdf --quals quals.json --grades grades.json \\
           [--portfolio portfolio.json] [--md report.md] [--out report.json]
  3. Optional: have a second grader fill its own grades file, then measure how far the two agree:
       python3 screen_grade.py agree --quals quals.json --grades grades.json grades-2.json
     [VWC] target: the same letter and at least 90% of qualifications graded the same way.

grades.json:
  {"title": {"resume_title": "Software Engineer"},
   "industry": {"posting": "fintech", "evidence": "<exact resume quote or empty>"},
   "grades": [{"id": "B1", "met": true, "evidence": "<exact resume quote>", "section": "experience"},
              {"id": "P1", "met": false, "evidence": ""}]}

Exit codes: 0 graded, 1 no grade (parse gate failed), 2 bad input or refused.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from jobdata import docs, lexicon, net, postings  # noqa: E402

BASIC_H = re.compile(r"\b(requirements?|required|qualifications?|must[- ]haves?|what you(?:'ll)? (?:need|bring)|"
                     r"who you are|you have|minimum|basic qualifications?|what we(?:'re| are) looking for)\b", re.I)
PREF_H = re.compile(r"\b(preferred|nice[- ]to[- ]haves?|bonus|plus(?:es)?|desired|ideally|extra credit|"
                    r"good to have|it would be great)\b", re.I)
OTHER_H = re.compile(r"\b(benefits?|perks|about (?:us|the company|the team)|compensation|salary|what we offer|"
                     r"responsibilities|what you(?:'ll)? do|the role|equal opportunity|eeo|our values|how to apply)\b", re.I)
BULLET = re.compile(r"^\s*(?:[-*•●▪–]|\d{1,2}[.)])\s+")

KNOCKOUTS = [  # [vendor] application questions that screen out before any ranking
    ("work authorization", re.compile(r"\b(authori[sz]ed to work|work authori[sz]ation|right to work|sponsor(?:ship)?|visa)\b", re.I)),
    ("security clearance", re.compile(r"\b(clearance|ts/sci|top secret|secret clearance|public trust|polygraph)\b", re.I)),
    ("minimum years", re.compile(r"\b(\d{1,2})\+?\s*(?:or more\s+)?years?\b", re.I)),
    ("location or on-site", re.compile(r"\b(on-?site|in[- ]office|hybrid|relocat\w*|must (?:live|reside)|based in)\b", re.I)),
    ("degree", re.compile(r"\b(bachelor'?s?|master'?s?|ph\.?d|b\.?s\.?|degree)\b", re.I)),
    ("citizenship", re.compile(r"\b(u\.?s\.? citizen(?:ship)?|citizenship)\b", re.I)),
]

FORM_ONLY = re.compile(r"\b(authori[sz]ed to work|work authori[sz]ation|sponsorship|right to work|u\.?s\.? citizen|"
                       r"background check|drug (?:test|screen)|equal opportunity)\b", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?<![\d-])(?:\+\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{4}(?![\d-])")  # US and international
MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_RANGE = re.compile(rf"((?:{MONTHS}\s+)?(?:19|20)\d{{2}})\s*(?:-|–|—|to)\s*((?:{MONTHS}\s+)?(?:19|20)\d{{2}}|present|current|now)", re.I)
# Headings people really use beside the standard four: "Leadership", "Teaching & Publications", "Awards, Certifications & Service"
_MORE = r"(?:leadership|teaching|publications?|awards?|honors?|certifications?|licenses?|military service|service|activities|training|languages|community)"
SECTION_NAMES = re.compile(r"^\s*(professional\s+|work\s+|relevant\s+|earlier\s+|additional\s+|other\s+|prior\s+|previous\s+)?"
                           r"(experience|employment|work history|projects?|education|skills|technical skills|summary|volunteer\w*|"
                           r"open source|leadership experience|" + _MORE + r"(?:\s*(?:,\s*and|,|&|and)\s*" + _MORE + r")*)\s*:?\s*$", re.I)
# "I" the pronoun, not the I in "Google I/O" or "Engineer I, Acme"
PRONOUN = re.compile(r"(?<![\w/])I(?=['’]|\s+[a-z])|\b(?:me|my|mine|myself)\b")
YEARS_CLAIM = re.compile(r"\b(\d{1,2})\+?\s*(?:years|yrs)\b", re.I)
WEAK_START = re.compile(r"^(responsible for|duties included|worked on|helped|assisted with|tasked with|in charge of)\b", re.I)
SENIORITY = re.compile(r"\b(senior|sr\.?|junior|jr\.?|staff|principal|lead|ii|iii|iv|i|intern|associate|mid[- ]level|entry[- ]level)\b", re.I)
EXP_SECTIONS = {"experience", "employment", "work history", "projects", "project", "volunteer", "volunteering",
                "volunteer experience", "open source", "leadership", "leadership experience"}


def refuse(msg: str) -> None:
    print(f"REFUSED: {msg}", file=sys.stderr)
    sys.exit(2)


def in_git_repo(path: pathlib.Path) -> bool:
    try:
        r = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and r.stdout.strip() == "true"
    except (OSError, subprocess.TimeoutExpired):
        return False


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("’", "'").replace("–", "-").replace("—", "-")).strip().lower()


# ---------------------------------------------------------------- step 1: split the posting

def fetch_posting(kind: str, board: str, job: str) -> tuple[str, str]:
    """Return (title, plain text) from a public, keyless job board."""
    if kind == "greenhouse":
        d = net.fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job}?content=true")
        import html
        return d.get("title", ""), postings.html_to_text(html.unescape(d.get("content", "")))
    if kind == "lever":
        d = net.fetch_json(f"https://api.lever.co/v0/postings/{board}/{job}?mode=json")
        lists = "\n".join(f"{x.get('text', '')}\n" + postings.html_to_text(x.get("content", "")) for x in d.get("lists", []))
        return d.get("text", ""), "\n".join([d.get("descriptionPlain", ""), lists, d.get("additionalPlain", "")])
    if kind == "ashby":
        d = net.fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=false")
        for j in d.get("jobs", []):
            if j.get("id") == job or j.get("jobUrl", "").rstrip("/").endswith(job):
                return j.get("title", ""), j.get("descriptionPlain") or postings.html_to_text(j.get("descriptionHtml", ""))
        raise net.FetchError(f"job {job} not found on Ashby board {board}")
    raise ValueError(kind)


CRITICAL_MENTIONS = 3  # [VWC] deck M2 "Decode the job description": 3+ mentions is critical


def decode_posting(text: str, basic: list[str], pref: list[str]) -> list[dict]:
    """Highlight, sort, count: every named skill, how often the posting says it, and where."""
    vocab = lexicon.build_vocab()
    out = []
    for skill in sorted(lexicon.find_skills(text, vocab)):
        hits = sum(len(lexicon._pattern(alias).findall(text)) for alias in vocab[skill])
        in_basic = any(skill in lexicon.find_skills(b, vocab) for b in basic)
        in_pref = any(skill in lexicon.find_skills(b, vocab) for b in pref)
        tier = "required" if in_basic else "preferred" if in_pref else "nice-to-have"
        out.append({"skill": skill, "mentions": hits, "tier": tier, "critical": hits >= CRITICAL_MENTIONS})
    tier_rank = {"required": 0, "preferred": 1, "nice-to-have": 2}
    return sorted(out, key=lambda d: (not d["critical"], tier_rank[d["tier"]], -d["mentions"], d["skill"]))


def split_posting(title: str, text: str) -> dict:
    basic, pref, form_only, current = [], [], [], None
    text = text.replace("\u2019", "'").replace("\u2018", "'")  # "What you\u2019ll bring" is a header too
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        is_bullet = bool(BULLET.match(line))
        body = BULLET.sub("", line).strip()
        if not is_bullet and len(body) <= 90:
            if PREF_H.search(body):
                current = "preferred"
                continue
            if BASIC_H.search(body):
                current = "basic"
                continue
            if OTHER_H.search(body) or body.endswith(":"):
                current = None
                continue
        if current and (is_bullet or len(body) > 25):
            item = body.rstrip(";.")
            if FORM_ONLY.search(item):  # answered on the application form, not graded from the resume
                form_only.append(item)
                continue
            if PREF_H.search(item) and current == "basic" and re.match(r"^(bonus|plus|nice)", item, re.I):
                pref.append(item)
            else:
                (basic if current == "basic" else pref).append(item)
    knock = []
    for name, rx in KNOCKOUTS:
        for item in form_only + basic + pref + [text]:
            m = rx.search(item)
            if m:
                quote = item if item is not text else text[max(0, m.start() - 60): m.end() + 60].strip()
                entry = {"knockout": name, "posting_says": re.sub(r"\s+", " ", quote)[:220]}
                if name == "minimum years":
                    entry["years"] = int(m.group(1))
                knock.append(entry)
                break
    return {
        "title": title,
        "basic": [{"id": f"B{i}", "text": t} for i, t in enumerate(basic, 1)],
        "preferred": [{"id": f"P{i}", "text": t} for i, t in enumerate(pref, 1)],
        "knockouts": knock,
        "decode": decode_posting(text, basic, pref),
        "decode_rule": f"[VWC] a skill the posting names {CRITICAL_MENTIONS}+ times is critical: map each one to "
                       "proof (step 4, Map) before you apply.",
        "split_rule": "[VWC] lines under a header like Preferred / Nice to have / Bonus are preferred; lines under "
                      "Requirements / Qualifications / What you bring are basic. Check the split before grading.",
        "split_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------- step 2: grade

def sections(text: str) -> list[tuple[str, str]]:
    """Return [(section_name, line)] for every non-empty resume line.

    A bullet that wraps onto more lines comes back as one line, so a skill on the first line and its
    number on the second are graded together."""
    cur, out = "header", []
    bullet_indent = None  # indent of the bullet the next line may continue
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            bullet_indent = None
            continue
        m = SECTION_NAMES.match(line)
        if m:
            cur, bullet_indent = m.group(2).lower(), None
            continue
        indent = len(raw) - len(raw.lstrip())
        if BULLET.match(line):
            bullet_indent = indent
        elif bullet_indent is not None and out and not DATE_RANGE.search(line) and (
                indent > bullet_indent or (line[0].islower() and out[-1][1][-1] not in ".;:!?"
                                           and "|" not in line and "http" not in line)):
            out[-1] = (cur, out[-1][1] + " " + line)
            continue
        else:
            bullet_indent = None
        out.append((cur, line))
    return out


def quote_found(quote: str, text: str) -> bool:
    hay = norm(text)
    parts = [norm(p) for p in quote.split("...") if norm(p)]
    if sum(len(p) for p in parts) < 8:  # "" and "..." quote nothing
        return False
    pos = 0
    for p in parts:
        i = hay.find(p, pos)
        if i < 0:
            return False
        pos = i + len(p)
    return True


def names_the_skill(qual: str, quote: str, lines: list[tuple[str, str]], vocab: dict) -> tuple[bool, set]:
    """A quote can be on the resume and still not answer the qualification. When the qualification names
    skills the kit knows, the quoted lines must name at least one of them: React doesn't prove Vue. [VWC]"""
    want = lexicon.find_skills(qual, vocab)
    if not want:
        return True, want
    parts = [norm(p)[:40] for p in quote.split("...") if norm(p)]
    around = " ".join(l for _, l in lines if any(p in norm(l) for p in parts))
    return bool(want & lexicon.find_skills(quote + " " + around, vocab)), want


def section_of(quote: str, lines: list[tuple[str, str]]) -> str:
    first = norm(quote.split("...")[0])[:60]
    for sec, line in lines:
        if first and first[:40] in norm(line):
            return "experience" if sec in EXP_SECTIONS else sec
    return "unknown"


def parse_gate(text: str, lines: list[tuple[str, str]]) -> list[dict]:
    """[vendor] HiredScore gives no grade to resumes it can't read. These are testable proxies."""
    words = len(re.findall(r"\w+", text))
    named = {sec for sec, _ in lines}
    checks = [
        ("Readable text", words >= 150, f"{words} words extracted", "Export a text-based PDF or .docx; scanned images and text in graphics can't be read."),
        ("Email", bool(EMAIL.search(text)), "", "Put your email in the top lines as plain text, not in a header or footer. [HES: missing contact info is a top-five mistake]"),
        ("Phone", bool(PHONE.search(text)), "", "Put your phone number in the top lines as plain text. [HES]"),
        ("Standard section headings", len(named & {"experience", "employment", "work history", "projects", "project"}) >= 1 and
         len(named & {"education", "skills", "technical skills"}) >= 1, ", ".join(sorted(named - {"header"})) or "none found",
         "Use standard headings on their own line: Experience, Projects, Skills, Education."),
        ("Dates parse", len(DATE_RANGE.findall(text)) >= 1, f"{len(DATE_RANGE.findall(text))} date ranges", "Write dates as 'Jan 2023 - Present' or '2021 - 2023' on the role line."),
    ]
    wide = sum(1 for _, l in lines if re.search(r"\S {4,}\S.* {4,}\S", l))
    checks.append(("Single column", wide <= max(3, len(lines) // 10), f"{wide} lines look like side-by-side columns",
                   "Use one column. Tables and side-by-side columns get read out of order."))
    # A file with no email or phone still parses, so those two are reported as fixes and block no score.
    return [{"check": c, "ok": ok, "detail": d, "fix": "" if ok else f, "blocks": c not in ("Email", "Phone")}
            for c, ok, d, f in checks]


def readable(gate: list[dict]) -> bool:
    """One rule for both scores: the file gets a score or a grade only if every blocking check passes."""
    return all(c["ok"] for c in gate if c.get("blocks", True))


def _end_month(end: str) -> int:
    """The end of a date range as a month count; Present sorts after every date."""
    y = re.search(r"(19|20)\d{2}", end)
    if not y:
        return 10 ** 6
    m = re.match(rf"\s*({MONTHS})", end, re.I)
    mon = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(m.group(1)[:3].lower()) + 1 if m else 12
    return int(y.group(0)) * 12 + mon


def format_checks(text: str, lines: list[tuple[str, str]]) -> list[dict]:
    out = []
    bullets = [(s, BULLET.sub("", l)) for s, l in lines if BULLET.match(l) or s in EXP_SECTIONS]
    pron = [l for s, l in bullets if PRONOUN.search(l)]
    out.append({"rule": "No personal pronouns", "source": "HES", "ok": not pron, "examples": pron[:3]})
    weak = [l for s, l in bullets if WEAK_START.match(l)]
    out.append({"rule": "Open each bullet with an action verb, not 'Responsible for'", "source": "HES", "ok": not weak, "examples": weak[:3]})
    date_first = [l for s, l in lines if s != "header" and DATE_RANGE.match(l)
                  and len(re.findall(r"[A-Za-z]{3,}", DATE_RANGE.sub("", l, count=1))) >= 2]
    out.append({"rule": "Don't start lines with a date", "source": "HES", "ok": not date_first, "examples": date_first[:3]})
    by_sec: dict[str, list[int]] = {}  # order is judged inside each section: a 2025 project under a 2020 job is fine
    for s, l in lines:
        for m in DATE_RANGE.finditer(l):
            by_sec.setdefault(s, []).append(_end_month(m.group(2)))
    # Most recent first means by end date: two roles that both run to Present are in order either way
    out_of_order = {s: ends for s, ends in by_sec.items() if any(a < b for a, b in zip(ends, ends[1:]))}
    out.append({"rule": "Reverse chronological order (most recent first)", "source": "HES", "ok": not out_of_order,
                "examples": [f"{s}: a role that ended earlier is listed above one that ended later" for s in out_of_order]})
    numbered = [l for s, l in lines if re.match(r"^(?:[IVX]+|[A-H])[.)]\s+[A-Z]", l)]
    out.append({"rule": "Don't number or letter sections", "source": "HES", "ok": not numbered, "examples": numbered[:3]})
    refs = [l for s, l in lines if re.search(r"references (?:available|upon request)", l, re.I)]
    out.append({"rule": "Don't list references", "source": "HES", "ok": not refs, "examples": refs[:2]})
    bad_years = [m.group(0) for m in YEARS_CLAIM.finditer(text) if int(m.group(1)) not in (5, 10)]
    out.append({"rule": "Experience length says 5+ or 10+ only, never more than 10+", "source": "VWC", "ok": not bad_years,
                "examples": bad_years[:3]})
    return out


def manipulation_flags(text: str, lines: list[tuple[str, str]], vocab: dict) -> list[dict]:
    """Old keyword tricks. Some screeners now flag them; at best they add nothing."""
    flags = []
    for sec, l in lines:
        items = [x for x in re.split(r"[,|;•]", l) if x.strip()]
        if sec not in {"skills", "technical skills", "header"} and len(items) >= 12:
            flags.append({"flag": "Keyword block outside Skills", "line": l[:160]})
    for skill in lexicon.find_skills(text, vocab):
        hits = sum(len(lexicon._pattern(alias).findall(text)) for alias in vocab[skill])
        if hits > 10:  # [VWC] heuristic: past ten mentions reads as stuffing, not evidence
            flags.append({"flag": f"{skill} appears {hits} times", "line": ""})
    return flags


def total_years(text: str) -> float:
    now = dt.date.today().year
    spans = []
    for m in DATE_RANGE.finditer(text):
        a = re.search(r"(19|20)\d{2}", m.group(1))
        b = re.search(r"(19|20)\d{2}", m.group(2))
        if a:
            spans.append((int(a.group(0)), int(b.group(0)) if b else now))
    years = set()
    for a, b in spans:
        years.update(range(a, max(a, b)))
    return float(len(years))


def title_alignment(posting_title: str, resume_title: str, text: str) -> dict:
    """[vendor] Greenhouse names job titles as a matching criterion. Exact weight isn't public."""
    def core(t):
        return {w for w in re.findall(r"[a-z+#]+", SENIORITY.sub(" ", (t or "").lower())) if len(w) > 2}
    p, r = core(posting_title), core(resume_title)
    top = " ".join(l for l in text.splitlines()[:8])
    if p and p <= core(top) | r:
        verdict = "aligned"
    elif p & (r | core(top)):
        verdict = "partial"
    else:
        verdict = "not aligned"
    return {"posting_title": posting_title, "resume_title": resume_title, "verdict": verdict,
            "fix": "" if verdict == "aligned" else f"Use the posting's role words (\"{SENIORITY.sub('', posting_title).strip()}\") in your headline and, where true, your title line."}


def portfolio_hits(qual_text: str, record: dict | None, vocab: dict) -> list[str]:
    if not record:
        return []
    want = lexicon.find_skills(qual_text, vocab)
    if not want:
        return []
    hits = []
    for a in record.get("artifacts", []):
        have = lexicon.find_skills(" ".join(a.get("skills", [])) + " " + a.get("summary", ""), vocab)
        if want & have:
            hits.append(f"{a.get('name', 'artifact')} (depth {a.get('depth', '?')}): {', '.join(sorted(want & have))}")
    return hits


def grade_letter(bm: int, bt: int, pm: int, pt: int) -> tuple[str, str]:
    """Workday HiredScore's documented definitions (Reference: Candidate Grades, 2023-06-23):
    A all basic + most preferred + average match above a threshold; B all basic;
    C most but not all basic; D not most basic. "Most" is read as more than half [VWC].
    The A threshold on average match isn't published, so A here means only the first two parts."""
    if bt == 0:
        return "?", "The posting lists no basic qualifications the split could find. Check quals.json by hand."
    if bm == bt and (pt == 0 or pm * 2 > pt):
        return "A", ("All basic met, plus most preferred. [vendor definition; 'most' read as more than half (VWC). "
                     "HiredScore also requires an average match above a threshold it doesn't publish, so treat A as A or B.]")
    if bm == bt:
        return "B", "All basic qualifications met. [vendor definition]"
    if bm * 2 > bt:
        return "C", "Most but not all basic qualifications met. [vendor definition]"
    return "D", "Half or fewer of the basic qualifications met. [vendor definition: does not meet most basic]"


def grade(resume_path: str, quals: dict, grades: dict, record: dict | None) -> dict:
    text = docs.read_text(resume_path)
    lines = sections(text)
    vocab = lexicon.build_vocab()
    gate = parse_gate(text, lines)
    by_id = {g.get("id"): g for g in grades.get("grades", [])}
    problems, rows = [], []
    for kind in ("basic", "preferred"):
        for q in quals.get(kind, []):
            g = by_id.get(q["id"])
            if g is None:
                problems.append(f"{q['id']} has no grade")
                continue
            met, ev = bool(g.get("met")), (g.get("evidence") or "").strip()
            verified = quote_found(ev, text)
            if met and not verified:
                problems.append(f"{q['id']} is marked met but its quote isn't on the resume: {ev[:80]!r}")
            elif met:
                named, want = names_the_skill(q["text"], ev, lines, vocab)
                if not named:
                    problems.append(f"{q['id']} is marked met but its quote names none of the skills the "
                                    f"qualification asks for ({', '.join(sorted(want))}): {ev[:80]!r}")
            sec = section_of(ev, lines) if verified else ""
            rows.append({"id": q["id"], "kind": kind, "qualification": q["text"], "met": met and verified,
                         "evidence": ev if verified else "", "section": sec,
                         "skills_list_only": met and verified and sec in {"skills", "technical skills", "summary"},
                         "portfolio_shows": [] if (met and verified) else portfolio_hits(q["text"], record, vocab)})
    if problems:
        return {"refused": problems}
    bm = sum(r["met"] for r in rows if r["kind"] == "basic")
    bt = sum(1 for r in rows if r["kind"] == "basic")
    pm = sum(r["met"] for r in rows if r["kind"] == "preferred")
    pt = sum(1 for r in rows if r["kind"] == "preferred")
    letter, why = grade_letter(bm, bt, pm, pt) if readable(gate) else ("No grade", "Fix the format first: the parse gate failed. [vendor: no grade for unreadable formats]")
    yrs = total_years("\n".join(l for s, l in lines if s in EXP_SECTIONS - {"projects", "project"}))
    knock = []
    for k in quals.get("knockouts", []):
        e = dict(k)
        if k["knockout"] == "minimum years":
            e["resume_shows"] = f"about {yrs:.0f} years of dated Experience roles (any field; count only what the posting means)"
            e["ok"] = yrs >= k.get("years", 0)
        else:
            e["resume_shows"] = "answer this on the application form; keep it consistent with the resume"
            e["ok"] = None
        knock.append(e)
    ind = grades.get("industry") or {}
    ind_ok = quote_found(ind.get("evidence", ""), text)
    return {
        "grade": letter, "why": why,
        "basic": f"{bm}/{bt}", "preferred": f"{pm}/{pt}",
        "rows": rows,
        "title": title_alignment(quals.get("title", ""), (grades.get("title") or {}).get("resume_title", ""), text),
        "industry": {"posting": ind.get("posting", ""), "evidence": ind.get("evidence", "") if ind_ok else "",
                     "verdict": "shown" if ind_ok else ("not shown" if ind.get("posting") else "not graded")},
        "knockouts": knock,
        "parse_gate": gate,
        "format": format_checks(text, lines),
        "manipulation": manipulation_flags(text, lines, vocab),
        "graded_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }


def letter_from(quals: dict, grades: dict) -> tuple[str, dict]:
    met = {g.get("id"): bool(g.get("met")) for g in grades.get("grades", [])}
    b = [met.get(q["id"], False) for q in quals.get("basic", [])]
    p = [met.get(q["id"], False) for q in quals.get("preferred", [])]
    ids = [q["id"] for q in quals.get("basic", []) + quals.get("preferred", [])]
    return grade_letter(sum(b), len(b), sum(p), len(p))[0], {i: met.get(i, False) for i in ids}


AGREE_TARGET = 0.9  # [VWC] two graders should mark at least 90% of qualifications the same way


def agreement(quals: dict, a: dict, b: dict) -> dict:
    """METHOD rule 5: measure how far two graders agree on the same resume and posting."""
    la, ma = letter_from(quals, a)
    lb, mb = letter_from(quals, b)
    differ = [i for i in ma if ma[i] != mb[i]]
    share = 1 - len(differ) / len(ma) if ma else 0.0
    return {"letters": [la, lb], "same_letter": la == lb, "agreement": round(share, 2), "differ": differ,
            "target": AGREE_TARGET, "ok": la == lb and share >= AGREE_TARGET}


def report_md(r: dict) -> str:
    L = [f"# Screen Grade: {r['grade']}", "", r["why"], "",
         f"Basic qualifications met: {r['basic']} · Preferred met: {r['preferred']} · Title: {r['title']['verdict']} · Industry: {r['industry']['verdict']}",
         "", "Not a hiring prediction. It mirrors the documented grading method; each employer sets its own weights.", ""]
    miss = [x for x in r["rows"] if not x["met"]]
    if miss:
        L += ["## Not met (fix in this order: basic first)", "", "| # | Qualification | Your portfolio shows |", "|---|---|---|"]
        for x in sorted(miss, key=lambda x: x["kind"] != "basic"):
            L.append(f"| {x['id']} | {x['qualification'][:110]} | {'; '.join(x['portfolio_shows']) or 'not in your portfolio yet'} |")
        L.append("")
    thin = [x for x in r["rows"] if x["skills_list_only"]]
    if thin:
        L += ["## Met only in Skills or Summary (move into a bullet with a result)", ""]
        L += [f"- {x['id']}: {x['qualification'][:100]}" for x in thin] + [""]
    if r["knockouts"]:
        L += ["## Knockout questions (answer these deliberately)", ""]
        for k in r["knockouts"]:
            mark = "" if k.get("ok") is None else (" · ok" if k["ok"] else " · check")
            L.append(f"- {k['knockout']}: \"{k['posting_says'][:120]}\" · {k['resume_shows']}{mark}")
        L.append("")
    if r["title"]["fix"]:
        L += ["## Title", "", r["title"]["fix"], ""]
    gate_bad = [c for c in r["parse_gate"] if not c["ok"]]
    fmt_bad = [f for f in r["format"] if not f["ok"]]
    if gate_bad or fmt_bad:
        L += ["## Format", ""]
        L += [f"- {c['check']}: {c['fix']} ({c['detail']})" for c in gate_bad]
        L += [f"- [{f['source']}] {f['rule']}: {'; '.join(map(str, f['examples']))[:160]}" for f in fmt_bad]
        L.append("")
    if r["manipulation"]:
        L += ["## Remove these (old keyword tricks)", ""] + [f"- {m['flag']} {m['line'][:100]}" for m in r["manipulation"]] + [""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("split", help="split a posting into qualifications and knockouts")
    s.add_argument("--posting", help="posting saved as plain text")
    s.add_argument("--title", default="", help="posting title (when using --posting)")
    for b in ("greenhouse", "lever", "ashby"):
        s.add_argument(f"--{b}", metavar="BOARD")
    s.add_argument("--job", help="job id on the board")
    s.add_argument("--out", required=True)
    g = sub.add_parser("grade", help="grade a resume from quals.json + grades.json")
    g.add_argument("--resume", required=True)
    g.add_argument("--quals", required=True)
    g.add_argument("--grades", required=True)
    g.add_argument("--portfolio", help="portfolio.json, to show which gaps your portfolio already proves")
    g.add_argument("--out")
    g.add_argument("--md")
    g.add_argument("--allow-repo", action="store_true", help="allow the resume and reports inside a private git repository")
    ag = sub.add_parser("agree", help="measure how far two graders agree on the same posting")
    ag.add_argument("--quals", required=True)
    ag.add_argument("--grades", required=True, nargs=2, metavar="GRADES")
    a = ap.parse_args(argv)

    if a.cmd == "agree":
        try:
            quals = json.loads(pathlib.Path(a.quals).read_text())
            one, two = (json.loads(pathlib.Path(x).read_text()) for x in a.grades)
        except (OSError, json.JSONDecodeError) as e:
            refuse(f"can't read input: {e}")
        r = agreement(quals, one, two)
        print(f"Letters: {r['letters'][0]} and {r['letters'][1]}. Graded the same way: {r['agreement']:.0%} "
              f"(target {AGREE_TARGET:.0%} and the same letter). [VWC]")
        if r["differ"]:
            print("Disagree on: " + ", ".join(r["differ"]) + ". Reread the rule for each, regrade both, and "
                  "tighten the rule if they still differ. Never bend it for one resume.")
        return 0 if r["ok"] else 1

    if a.cmd == "split":
        try:
            if a.posting:
                title, text = a.title, pathlib.Path(a.posting).expanduser().read_text(errors="replace")
                if a.posting.lower().endswith((".html", ".htm")):
                    text = postings.html_to_text(text)
            else:
                kind = next((b for b in ("greenhouse", "lever", "ashby") if getattr(a, b)), None)
                if not (kind and a.job):
                    ap.error("give --posting FILE, or one of --greenhouse/--lever/--ashby with --job")
                title, text = fetch_posting(kind, getattr(a, kind), a.job)
        except net.FetchError as e:
            print(f"STOPPED: couldn't fetch the posting ({e}). Save it as text and use --posting.", file=sys.stderr)
            return 2
        q = split_posting(title, text)
        pathlib.Path(a.out).write_text(json.dumps(q, indent=1))
        print(f"{len(q['basic'])} basic, {len(q['preferred'])} preferred, {len(q['knockouts'])} knockouts -> {a.out}")
        crit = [d for d in q["decode"] if d["critical"]]
        if crit:
            print("Critical (3+ mentions), map each to proof: " +
                  ", ".join(f"{d['skill']} x{d['mentions']} ({d['tier']})" for d in crit))
        if not q["basic"]:
            print("No basic qualifications found. Open the file and move the requirement lines into 'basic'.")
        return 0

    resume = pathlib.Path(a.resume).expanduser().resolve()
    for p in [resume] + [pathlib.Path(x).expanduser().resolve() for x in (a.out, a.md) if x]:
        if not a.allow_repo and in_git_repo(p):
            refuse(f"{p} is inside a git repository. Keep resumes and reports out of repos (they end up on GitHub), "
                   "or pass --allow-repo if the repository is private.")
    try:
        quals = json.loads(pathlib.Path(a.quals).read_text())
        grades = json.loads(pathlib.Path(a.grades).read_text())
        record = json.loads(pathlib.Path(a.portfolio).expanduser().read_text()) if a.portfolio else None
    except (OSError, json.JSONDecodeError) as e:
        refuse(f"can't read input: {e}")
    r = grade(str(resume), quals, grades, record)
    if "refused" in r:
        refuse("fix these grades first:\n  " + "\n  ".join(r["refused"]))
    md = report_md(r)
    if a.out:
        pathlib.Path(a.out).write_text(json.dumps(r, indent=1))
    if a.md:
        pathlib.Path(a.md).write_text(md)
    print(md)
    return 1 if r["grade"] == "No grade" else 0


if __name__ == "__main__":
    sys.exit(main())
