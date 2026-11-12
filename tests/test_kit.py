"""Offline tests for the kit. Network calls are stubbed with fixtures.
Run: python3 -m unittest discover -s tests -v   (from the kit root)
"""
import csv
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "scripts"))

from jobdata import bls, demand, docs, lexicon, onet, postings  # noqa: E402
import friday_setup  # noqa: E402
import funnel  # noqa: E402
import sync_check  # noqa: E402


class TestOnetParse(unittest.TestCase):
    def test_tech_skills_flags(self):
        rows = onet.parse_tsv((FIX / "technology_skills.tsv").read_text())
        o = onet.Onet(version="30_2")
        o._cache["Technology Skills.txt"] = rows
        ts = o.technology_skills("15-1252.00")
        py = next(t for t in ts if t["skill"] == "Python")
        self.assertTrue(py["hot"] and py["in_demand"])
        self.assertEqual(len(ts), 6)

    def test_missing_code_raises(self):
        o = onet.Onet(version="30_2")
        o._cache["Technology Skills.txt"] = onet.parse_tsv((FIX / "technology_skills.tsv").read_text())
        with self.assertRaises(Exception):
            o.technology_skills("99-9999.00")


class TestBls(unittest.TestCase):
    def test_parse_projections(self):
        rows = bls.parse_projections((FIX / "projections.html").read_text())
        sd = rows["15-1252"]
        self.assertEqual(sd["growth_pct_10yr"], 10.0)
        self.assertEqual(sd["annual_openings_thousands"], 50.0)
        self.assertEqual(sd["median_wage"], 100000.0)

    def test_soc6(self):
        self.assertEqual(bls.soc6("15-1252.00"), "15-1252")

    def test_fetch_failure_stops(self):
        with mock.patch.object(bls, "fetch", side_effect=bls.FetchError("blocked")):
            with self.assertRaises(bls.FetchError):
                bls.Bls().projections("15-1252.00")


class TestLexicon(unittest.TestCase):
    def test_no_false_java_from_javascript(self):
        found = lexicon.find_skills("Strong JavaScript skills", lexicon.CURATED)
        self.assertIn("JavaScript", found)
        self.assertNotIn("Java", found)

    def test_aliases(self):
        found = lexicon.find_skills("Postgres + pgvector, k8s, GitHub Actions", lexicon.CURATED)
        for s in ("PostgreSQL", "pgvector", "Kubernetes", "CI/CD"):
            self.assertIn(s, found)


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.tech = onet.Onet(version="x")
        self.tech._cache["Technology Skills.txt"] = onet.parse_tsv((FIX / "technology_skills.tsv").read_text())
        self.rows = self.tech.technology_skills("15-1252.00")
        self.posts = postings.load_folder(FIX / "postings")

    def test_posting_skills_outrank_onet_only(self):
        d, _ = demand.build_demand(self.rows, self.posts, top=40)
        names = [x.skill for x in d]
        # LangGraph is not in this O*NET fixture but 2 of 3 postings ask for it.
        self.assertIn("LangGraph", names)
        self.assertLess(names.index("Python"), names.index("Kubernetes"))

    def test_score_without_postings_uses_onet(self):
        d, _ = demand.build_demand(self.rows, [], top=10)
        self.assertTrue(all(x.posting_share == 0 for x in d))
        self.assertTrue(d)


class TestScreenGrade(unittest.TestCase):
    """Per-posting Screen Grade, modeled on Workday HiredScore's documented A-D grades."""

    def setUp(self):
        import screen_grade
        self.sg = screen_grade
        self.quals = screen_grade.split_posting("Software Engineer, Platform",
                                                (FIX / "screen_posting.txt").read_text())
        self.resume = str(FIX / "screen_resume.txt")
        self.record = json.loads((FIX / "portfolio.json").read_text())

    def grades(self, met_ids, quotes=None):
        quotes = quotes or {}
        good = {"B1": "Software Engineer, Example Logistics, Jan 2022 - Present",
                "B2": "Designed PostgreSQL schemas and SQL reports used by 12 analysts",
                "B3": "Moved nightly batch jobs to AWS Lambda with Terraform",
                "B4": "Wrote the GitHub Actions CI/CD pipeline",
                "P1": "Docker, GitHub Actions, Kubernetes",
                "P2": "Built an evaluation harness for a retrieval assistant"}
        rows = []
        for q in self.quals["basic"] + self.quals["preferred"]:
            m = q["id"] in met_ids
            rows.append({"id": q["id"], "met": m, "evidence": quotes.get(q["id"], good.get(q["id"], "")) if m else ""})
        return {"title": {"resume_title": "Software Engineer"}, "industry": {"posting": "fintech", "evidence": ""},
                "grades": rows}

    def test_split_basic_preferred_and_knockouts(self):
        self.assertEqual(len(self.quals["basic"]), 4)
        self.assertEqual(len(self.quals["preferred"]), 3)
        kinds = {k["knockout"] for k in self.quals["knockouts"]}
        self.assertIn("work authorization", kinds)
        self.assertIn("minimum years", kinds)
        self.assertFalse(any("authorized" in q["text"] for q in self.quals["basic"]))

    def test_letters_follow_vendor_definitions(self):
        gl = self.sg.grade_letter
        self.assertEqual(gl(4, 4, 2, 3)[0], "A")   # all basic + most preferred
        self.assertEqual(gl(4, 4, 1, 3)[0], "B")   # all basic
        self.assertEqual(gl(3, 4, 3, 3)[0], "C")   # most, not all, basic
        self.assertEqual(gl(2, 4, 3, 3)[0], "D")   # half is not most
        self.assertEqual(gl(0, 4, 0, 3)[0], "D")

    def test_grade_with_portfolio_hit(self):
        r = self.sg.grade(self.resume, self.quals, self.grades({"B1", "B2", "B3", "B4", "P1"}), self.record)
        self.assertEqual(r["grade"], "B")
        self.assertEqual((r["basic"], r["preferred"]), ("4/4", "1/3"))
        p1 = next(x for x in r["rows"] if x["id"] == "P1")
        self.assertTrue(p1["skills_list_only"])
        p2 = next(x for x in r["rows"] if x["id"] == "P2")
        self.assertTrue(any("rag-eval-harness" in h for h in p2["portfolio_shows"]))
        self.assertIn("# Screen Grade: B", self.sg.report_md(r))

    def test_refuses_a_quote_not_on_the_resume(self):
        g = self.grades({"B1", "B2", "B3", "B4"}, {"B3": "Ran Kubernetes clusters on GCP for 5 years"})
        r = self.sg.grade(self.resume, self.quals, g, self.record)
        self.assertIn("refused", r)
        self.assertTrue(any("B3" in m for m in r["refused"]))

    def test_refuses_missing_grades(self):
        g = self.grades({"B1"})
        g["grades"] = g["grades"][:2]
        self.assertIn("refused", self.sg.grade(self.resume, self.quals, g, self.record))

    def test_parse_gate_gives_no_grade(self):
        with tempfile.TemporaryDirectory() as td:
            thin = pathlib.Path(td) / "thin.txt"
            thin.write_text("Jordan Sample\nPython developer\nSkills: Python, SQL, AWS\n")
            r = self.sg.grade(str(thin), self.quals, self.grades(set()), None)
        self.assertEqual(r["grade"], "No grade")

    def test_hes_and_years_checks(self):
        text = (FIX / "screen_resume.txt").read_text()
        rules = {f["rule"]: f["ok"] for f in self.sg.format_checks(text, self.sg.sections(text))}
        self.assertTrue(rules["No personal pronouns"])
        self.assertTrue(rules["Experience length says 5+ or 10+ only, never more than 10+"])
        bad = text.replace("10+ years", "12 years")
        rules = {f["rule"]: f["ok"] for f in self.sg.format_checks(bad, self.sg.sections(bad))}
        self.assertFalse(rules["Experience length says 5+ or 10+ only, never more than 10+"])

    def test_refuses_inside_a_git_repo(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-q", td], check=True)
            res = pathlib.Path(td) / "resume.txt"
            res.write_text((FIX / "screen_resume.txt").read_text())
            q = pathlib.Path(td).parent / f"q-{pathlib.Path(td).name}.json"
            g = pathlib.Path(td).parent / f"g-{pathlib.Path(td).name}.json"
            q.write_text(json.dumps(self.quals))
            g.write_text(json.dumps(self.grades(set())))
            try:
                with self.assertRaises(SystemExit) as cm:
                    self.sg.main(["grade", "--resume", str(res), "--quals", str(q), "--grades", str(g)])
                self.assertEqual(cm.exception.code, 2)
            finally:
                q.unlink(); g.unlink()

    def test_allow_repo_grades_inside_a_private_repo(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-q", td], check=True)
            res = pathlib.Path(td) / "resume.txt"
            res.write_text((FIX / "screen_resume.txt").read_text())
            q = pathlib.Path(td) / "quals.json"
            g = pathlib.Path(td) / "grades.json"
            md = pathlib.Path(td) / "screen.md"
            q.write_text(json.dumps(self.quals))
            g.write_text(json.dumps(self.grades({"B1", "B2", "B3", "B4"})))
            self.sg.main(["grade", "--resume", str(res), "--quals", str(q), "--grades", str(g),
                          "--md", str(md), "--allow-repo"])
            self.assertIn("Screen Grade", md.read_text())


class TestFunnel(unittest.TestCase):
    def test_lifecycle_and_report(self):
        with tempfile.TemporaryDirectory() as td:
            f = str(pathlib.Path(td) / "f.csv")
            funnel.main(["init", "--file", f])
            funnel.main(["add", "--file", f, "--company", "A", "--role", "AI Eng", "--channel", "referral",
                         "--artifact", "rag"])
            funnel.main(["add", "--file", f, "--company", "B", "--role", "AI Eng", "--channel", "cold"])
            funnel.main(["move", "--file", f, "--id", "1", "--stage", "offer"])
            funnel.main(["close", "--file", f, "--id", "2", "--status", "ghosted"])
            with open(f) as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]["status"], "offer")
            md = funnel.build_report(rows, None)
            self.assertIn("| referral | 1 |", md)
            self.assertIn("Portfolio effect", md)


class TestMarketSnapshotStopsOffline(unittest.TestCase):
    def test_cli_exits_3_when_onet_unreachable(self):
        import market_snapshot
        with mock.patch.object(onet, "fetch", side_effect=onet.FetchError("blocked")):
            rc = market_snapshot.main(["--roles", "web developer"])
        self.assertEqual(rc, 3)


class TestFunnelResumeVersions(unittest.TestCase):
    def test_by_resume_version_and_old_lane_column(self):
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "f.csv"
            # An older tracker that still has a "lane" column must keep working.
            f.write_text("id,date_applied,company,role,lane,channel,stage,stage_date,status,resume_version,"
                         "artifact_shared,url,lesson,notes\n"
                         "1,2026-10-01,A,Dev,ai,referral,screen,2026-10-02,active,web-v1,,,,\n")
            funnel.main(["add", "--file", str(f), "--company", "B", "--role", "Dev", "--channel", "recruiter",
                         "--resume-version", "data-v1"])
            with open(f) as fh:
                rows = list(csv.DictReader(fh))
            self.assertNotIn("lane", rows[0])
            md = funnel.build_report(rows, None)
            self.assertIn("## By resume version", md)
            self.assertIn("| web-v1 | 1 | 1 | 0 |", md)


class TestFridaySetup(unittest.TestCase):
    def test_redaction(self):
        t = friday_setup.redact("key ghp_" + "a" * 36 + " mail me@corp.com host db1.corp api_key=abc123 10.0.0.5")
        for leaked in ("ghp_", "me@corp.com", "db1.corp", "abc123", "10.0.0.5"):
            self.assertNotIn(leaked, t)

    def test_render_hides_private_links(self):
        items = [{"title": "Add evals", "url": "https://github.com/x/secret/pull/1", "body": "<!-- tpl -->Did it",
                  "closedAt": "2026-10-30T00:00:00Z", "repository": {"nameWithOwner": "x/secret", "isPrivate": True}}]
        md = friday_setup.render(items, "2026-10-24", "2026-10-31", hide_private=True)
        self.assertIn("private repo", md)
        self.assertNotIn("x/secret", md)
        self.assertNotIn("tpl", md)

    def test_git_mode_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            repo = pathlib.Path(td) / "r"
            repo.mkdir()
            run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
            run("init", "-q")
            run("-c", "user.email=t@t.io", "-c", "user.name=T", "commit", "--allow-empty", "-q", "-m", "Ship evals")
            out = pathlib.Path(td) / "brag"
            args = ["--out", str(out), "--git-repos", str(repo), "--since", "2000-01-01", "--author", "t@t.io"]
            self.assertEqual(friday_setup.main(args), 0)
            files = [p for p in out.glob("*.md")]
            self.assertEqual(len(files), 1)
            self.assertIn("Ship evals", files[0].read_text())
            # Second run logs nothing new: already-seen items are skipped.
            friday_setup.main(args)
            newest = max(out.glob("*.md"), key=lambda q: q.stat().st_mtime_ns).read_text()
            self.assertIn("items: 0", newest)

    def test_refuses_to_write_inside_a_repo(self):
        with tempfile.TemporaryDirectory() as td:
            (pathlib.Path(td) / ".git").mkdir()
            rc = friday_setup.main(["--out", str(pathlib.Path(td) / "brag"), "--git-repos", td])
            self.assertEqual(rc, 2)
            self.assertFalse((pathlib.Path(td) / "brag").exists())

    def test_gh_visibility_tags_private_and_failed_source_keeps_window(self):
        calls = []

        def fake_run(cmd, timeout=90):
            calls.append(cmd)
            if cmd[:3] == ["gh", "auth", "status"]:
                return ""
            if "issues" in cmd:
                raise friday_setup.SourceError("rate limited")
            vis = cmd[cmd.index("--visibility") + 1]
            if vis == "private":
                return json.dumps([{"title": "Secret thing", "url": "https://github.com/x/priv/pull/2",
                                    "body": "", "closedAt": "2026-10-30T00:00:00Z", "number": 2,
                                    "repository": {"nameWithOwner": "x/priv"}}])
            return "[]"

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(friday_setup, "_run", side_effect=fake_run), \
                mock.patch.object(friday_setup.shutil, "which", return_value="/usr/bin/gh"):
            out = pathlib.Path(td) / "brag"
            rc = friday_setup.main(["--out", str(out), "--since", "2026-10-24", "--include-issues"])
            self.assertEqual(rc, 1)
            md = next(out.glob("*.md")).read_text()
            self.assertIn("private repo", md)
            self.assertNotIn("x/priv", md)
            state = json.loads((out / friday_setup.STATE).read_text())
            self.assertEqual(state["last_run"], "2026-10-24")


class TestPortfolioAsSourceOfTruth(unittest.TestCase):
    def _repo(self, td):
        repo = pathlib.Path(td) / "portfolio"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "portfolio.json").write_text("{}")
        return repo

    def test_portfolio_mode_writes_to_ignored_inbox(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            src = pathlib.Path(td) / "src"
            src.mkdir()
            run = lambda *a: subprocess.run(["git", "-C", str(src), *a], check=True, capture_output=True)
            run("init", "-q")
            run("-c", "user.email=t@t.io", "-c", "user.name=T", "commit", "--allow-empty", "-q", "-m", "Add evals")
            rc = friday_setup.main(["--portfolio", str(repo), "--git-repos", str(src), "--since", "2000-01-01",
                                    "--author", "t@t.io"])
            self.assertEqual(rc, 0)
            self.assertEqual(len(list((repo / "brag" / "inbox").glob("*.md"))), 1)
            gi = (repo / ".gitignore").read_text()
            self.assertIn("brag/inbox/", gi)
            self.assertIn(friday_setup.STATE, gi)

    def test_promote_gates_raw_and_unsafe_files(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            inbox = repo / "brag" / "inbox"
            inbox.mkdir(parents=True)
            raw = inbox / "2026-10-31.md"
            raw.write_text("---\nstatus: raw\n---\n- Impact: _(what changed for users)_\n")
            self.assertEqual(friday_setup.main(["--portfolio", str(repo), "--promote", str(raw)]), 2)
            leak = inbox / "2026-10-30.md"
            leak.write_text("---\nstatus: curated\n---\nShipped search, ping me at me@corp.com\n")
            self.assertEqual(friday_setup.main(["--portfolio", str(repo), "--promote", str(leak)]), 2)
            good = inbox / "2026-10-29.md"
            good.write_text("---\nstatus: curated\n---\nCut search latency 40% for 2,000 users.\n")
            self.assertEqual(friday_setup.main(["--portfolio", str(repo), "--promote", "brag/inbox/2026-10-29.md"]), 0)
            self.assertTrue((repo / "brag" / "entries" / "2026-10-29.md").exists())
            self.assertFalse(good.exists())

    def test_sync_check_finds_mismatches_offline(self):
        record = {"profile": {"target_role": "AI Engineer"},
                  "links": {"site": "https://pat.dev"},
                  "experience": [{"title": "Software Developer", "org": "Acme"}],
                  "artifacts": [{"name": "rag-eval-harness", "depth": 3, "url": "https://pat.dev/rag",
                                 "skills": ["Python", "RAG", "Evals", "FastAPI", "LangGraph"]},
                                {"name": "todo-local", "depth": 1, "skills": ["React"]}]}
        resume = docs.read_text(str(FIX / "candidate.txt")) + "\n15 years of experience\n"
        linkedin = "AI Engineer. Featured: rag eval harness https://pat.dev/rag. Software Developer at Acme."
        found = sync_check.check(record, resume, linkedin, None)
        bad = {(f["area"], f["item"], f["surface"]) for f in found if not f["ok"]}
        self.assertNotIn(("Headline", "AI Engineer", "resume"), bad)
        self.assertIn(("Artifacts", "rag-eval-harness", "resume"), bad)
        self.assertNotIn(("Artifacts", "rag-eval-harness", "LinkedIn"), bad)
        self.assertNotIn(("Artifacts", "todo-local", "resume"), {(a, i, s) for a, i, s in bad})
        self.assertIn(("Experience", "Software Developer at Acme", "resume"), bad)
        self.assertIn(("Skills", "Kubernetes", "resume"), bad)
        self.assertNotIn(("Skills", "LangGraph", "resume"), bad)
        self.assertIn(("Years", "15 years", "resume"), bad)
        self.assertIn("## Fix these", sync_check.report(found, []))


class TestScoringChain(unittest.TestCase):
    """The 7-step chain: resume, LinkedIn, GitHub, portfolio, composite, plan, rebuild. All offline."""

    def setUp(self):
        import resume_score
        tech = onet.Onet(version="x")
        tech._cache["Technology Skills.txt"] = onet.parse_tsv((FIX / "technology_skills.tsv").read_text())
        self.rows = tech.technology_skills("15-1252.00")
        self.posts = postings.load_folder(FIX / "postings")
        self.rs = resume_score.score(docs.read_text(str(FIX / "screen_resume.txt")), self.rows, self.posts, now=2026)
        self.td = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self.td.name)
        (self.tmp / "rs.json").write_text(json.dumps(self.rs))
        from jobdata import market
        self.mk = market
        self.market = market.load(str(self.tmp / "rs.json"))
        self.record = json.loads((ROOT / "templates" / "portfolio.json").read_text())

    def tearDown(self):
        self.td.cleanup()

    def assertSchema(self, r, surface):
        self.assertEqual(r["surface"], surface)
        self.assertTrue(0 <= r["score"] <= 100)
        for c in r["checks"]:
            self.assertTrue({"section", "check", "pass", "detail", "weight", "fix"} <= set(c))
            self.assertEqual(c["fix"] == "", c["pass"])

    def test_step1_resume_score_and_parse_gate(self):
        import resume_score
        self.assertSchema(self.rs, "resume")
        self.assertTrue(self.rs["skills"])
        self.assertTrue(all(k["grade"] in resume_score.GRADES for k in self.rs["skills"]))
        bad = resume_score.score(docs.read_text(str(FIX / "candidate.txt")), self.rows, self.posts, now=2026)
        self.assertIsNone(bad["score"])  # no score until the format parses

    def test_market_file_is_required_or_live(self):
        with self.assertRaises(ValueError):
            self.mk.load(None, None)
        (self.tmp / "empty.json").write_text("{}")
        with self.assertRaises(ValueError):
            self.mk.load(str(self.tmp / "empty.json"))
        share, found, missing = self.mk.coverage("Python and Docker", self.market, top=10)
        self.assertTrue(0 <= share <= 1)
        self.assertEqual(len(found) + len(missing), min(10, len(self.market["skills"])))

    def test_step2_linkedin_score(self):
        import linkedin_score
        text = (ROOT / "templates" / "linkedin-profile.txt").read_text()
        r = linkedin_score.score(text, self.market, self.record)
        self.assertSchema(r, "linkedin")
        sec = linkedin_score.split_profile(text)
        self.assertIn("Software Developer", sec["headline"])
        # the kit's own templates agree with each other
        self.assertFalse([c["check"] for c in r["checks"] if not c["pass"] and c["section"] in ("Headline", "Filters", "Experience")])
        self.assertTrue(all(c["pass"] for c in r["checks"] if c["check"].startswith("Every listed skill")))
        self.assertTrue(all(all(x.startswith("LinkedIn ") for x in v) for v in r["skill_evidence"].values()))
        empty = linkedin_score.score("Headline: Hi", self.market, self.record)
        self.assertLess(empty["score"], r["score"])

    def test_step3_github_score_stubbed(self):
        import base64
        import github_score
        readme = base64.b64encode(("# rag-eval-harness\n" + "Why: we chose pgvector. Python FastAPI RAG Evals Docker. " * 40).encode()).decode()
        pages = {
            "/users/pat": {"bio": "I build Python AI tools", "blog": "https://yourname.dev"},
            "/users/pat/repos?per_page=100&sort=pushed": [
                {"name": "rag-eval-harness", "fork": False, "pushed_at": "2026-10-30T00:00:00Z", "homepage": "https://yourname.dev/rag",
                 "description": "Policy QA with evals", "topics": ["rag", "python"], "language": "Python", "license": {"spdx_id": "MIT"}},
                {"name": "old-fork", "fork": True, "pushed_at": "2020-01-01T00:00:00Z"}],
            "/repos/pat/pat/readme": {"content": readme},
            "/repos/pat/rag-eval-harness/readme": {"content": readme},
            "/repos/pat/rag-eval-harness/contents/": [{"name": "tests"}, {"name": ".github"}, {"name": "app.py"}],
            "/repos/pat/rag-eval-harness/contents/.github/workflows": [{"name": "ci.yml"}],
        }

        class Fake(github_score.GitHub):
            def get(self, path):
                self.calls += 1
                if path not in pages:
                    raise github_score.FetchError(f"404 {path}")
                return pages[path]

        import datetime as dt
        r = github_score.score(Fake(), "pat", ["rag-eval-harness"], self.market, self.record, today=dt.date(2026, 11, 6))
        self.assertSchema(r, "github")
        ok = {c["check"]: c["pass"] for c in r["checks"] if c["section"] == "rag-eval-harness"}
        self.assertTrue(ok["Tests in the repo"] and ok["CI workflow"] and ok["Live demo link"])
        self.assertTrue(all(c["pass"] for c in r["checks"] if c["check"] == "Portfolio artifacts are the pinned repos"))
        r2 = github_score.score(Fake(), "pat", [], self.market, None, today=dt.date(2026, 11, 6))
        self.assertIn("Pins unknown", r2["note"])
        self.assertTrue(any("GitHub rag-eval-harness" in v for v in r["skill_evidence"].values()))  # pushed this year
        stale = github_score.score(Fake(), "pat", ["rag-eval-harness"], self.market, None, today=dt.date(2028, 6, 1))
        self.assertEqual(stale["skill_evidence"], {})  # no push in a year, no activity proof
        self.assertEqual(r2["repos"], ["rag-eval-harness"])  # forks skipped
        pages.update({  # a pin that lives under an organization is read from the organization
            "/repos/acme/platform": {"name": "platform", "owner": {"login": "acme"}, "fork": False, "pushed_at": "2026-10-30T00:00:00Z"},
            "/repos/acme/platform/readme": {"content": readme},
            "/repos/acme/platform/contents/": [{"name": "tests"}]})
        org = github_score.score(Fake(), "pat", ["acme/platform", "acme/gone"], self.market, None, today=dt.date(2026, 11, 6))
        self.assertEqual(org["repos"], ["platform"])
        self.assertIn("acme/gone", org["note"])
        self.assertTrue({c["check"]: c["pass"] for c in org["checks"] if c["section"] == "platform"}["Tests in the repo"])

    def test_proven_needs_github_or_linkedin(self):
        import resume_score
        import scorecard
        on_paper = [k for k in self.rs["skills"] if k["text_grade"] == "proven"]
        self.assertTrue(on_paper)
        self.assertFalse(self.rs["corroborated"])
        self.assertTrue(all(k["grade"] == "applied" for k in on_paper))  # a number alone isn't proof
        sk = on_paper[0]["skill"]
        gh = {"surface": "github", "score": 80, "checks": [], "skill_evidence": {sk: ["GitHub rag-eval-harness"]}}
        li = {"surface": "linkedin", "score": 80, "checks": [], "skill_evidence": {sk: ["LinkedIn Experience"]}}
        ev = resume_score.merge_evidence(li, gh)
        self.assertEqual(ev[sk], ["LinkedIn Experience", "GitHub rag-eval-harness"])
        r = resume_score.corroborate(json.loads(json.dumps(self.rs)), ev)
        self.assertEqual({k["skill"]: k["grade"] for k in r["skills"]}[sk], "proven")
        self.assertGreater(r["score"], self.rs["score"])
        listed = [k for k in self.rs["skills"] if k["text_grade"] == "listed"]
        if listed:  # outside proof never lifts a skill the resume only lists
            r2 = resume_score.corroborate(json.loads(json.dumps(self.rs)), {listed[0]["skill"]: ["GitHub x"]})
            self.assertEqual({k["skill"]: k["grade"] for k in r2["skills"]}[listed[0]["skill"]], "listed")
        c = scorecard.composite({"resume": dict(self.rs), "github": gh, "linkedin": li})
        self.assertEqual(c["inputs"]["resume"]["score"], r["score"])  # the composite applies the same rule
        self.assertEqual(self.rs["skills"][0].get("backed_by"), [])  # and doesn't change the step 1 file

    def test_step5_two_reads_and_resume_gate(self):
        import scorecard
        self.assertEqual(scorecard.READS["machine"], {"resume": 40, "linkedin": 35, "github": 15, "portfolio": 10})
        self.assertEqual(scorecard.READS["human"], {"portfolio": 35, "github": 30, "resume": 20, "linkedin": 15})
        self.assertEqual(scorecard.RESUME_GATE, 70)
        s = {"resume": {"surface": "resume", "score": 60, "checks": [], "skills": []},
             "linkedin": {"surface": "linkedin", "score": 80, "checks": []}}
        c = scorecard.composite(s)
        self.assertEqual(c["machine"]["score"], 69)  # (40*60 + 35*80) / 75, reweighted
        self.assertEqual(c["human"]["score"], 69)    # (20*60 + 15*80) / 35
        self.assertTrue(c["partial"])
        self.assertEqual(set(c["missing"]), {"github", "portfolio"})
        self.assertFalse(c["gate"]["passed"])        # 60 is under the gate, whatever the totals
        self.assertTrue(scorecard.composite(s, gate=55)["gate"]["passed"])
        full = dict(s, github={"surface": "github", "score": 100, "checks": []},
                    portfolio={"surface": "portfolio", "score": 100, "checks": []})
        cf = scorecard.composite(full)
        self.assertEqual((cf["machine"]["score"], cf["human"]["score"]), (77, 89))
        self.assertFalse(cf["gate"]["passed"])       # high totals don't clear a weak resume
        self.assertEqual(cf["total"]["out_of"], 400)  # the plain sum: 100 for each surface scored
        self.assertEqual(cf["total"]["score"], sum(v["score"] for v in full.values()))
        part = scorecard.composite({"linkedin": s["linkedin"]})
        self.assertEqual((part["total"]["score"], part["total"]["out_of"]), (s["linkedin"]["score"], 100))
        self.assertIn("Not in the total yet: Resume", scorecard.composite_md(part))
        w = {"machine": scorecard.parse_weights("resume=75,linkedin=25", "machine"), "human": scorecard.parse_weights(None, "human")}
        self.assertEqual(scorecard.composite(s, w)["machine"]["score"], 65)
        with self.assertRaises(ValueError):
            scorecard.parse_weights("twitter=10", "human")
        blocked = scorecard.composite({"resume": {"surface": "resume", "score": None}})
        self.assertIsNone(blocked["machine"]["score"])
        self.assertEqual(blocked["blocked"], ["resume"])
        self.assertFalse(blocked["gate"]["passed"])
        self.assertIn("parse gate", blocked["gate"]["note"])
        self.assertIsNone(scorecard.composite({"linkedin": s["linkedin"]})["gate"]["passed"])

    def test_step6_plan_ranks_by_points_left(self):
        import scorecard
        s = {"resume": dict(self.rs),
             "portfolio": {"surface": "portfolio", "score": 90, "checks": [
                 {"section": "Proof", "check": "Live demo", "pass": False, "detail": "", "weight": 2, "fix": "Portfolio: add a live demo."}]}}
        p = scorecard.plan(scorecard.composite(s))
        scored = [x for x in p["steps"] if x["status"] == "scored"]
        self.assertEqual(scored[0]["surface"], "resume")  # gate-failed resume first, or the biggest gap
        p2 = scorecard.plan(scorecard.composite({"resume": {"surface": "resume", "score": 95, "checks": [], "skills": []},
                                                 "portfolio": {"surface": "portfolio", "score": 50, "checks": []}}))
        self.assertEqual([x["surface"] for x in p2["steps"] if x["status"] == "scored"], ["portfolio", "resume"])
        p3 = scorecard.plan(scorecard.composite({"resume": {"surface": "resume", "score": 65, "checks": [], "skills": []},
                                                 "portfolio": {"surface": "portfolio", "score": 10, "checks": []}}))
        self.assertEqual(p3["steps"][0]["surface"], "resume")  # gate beats a bigger portfolio gap
        self.assertTrue(p3["steps"][0]["gate"])
        self.assertEqual({x["surface"]: x["skill"] for x in p["steps"]}["resume"], "resume-rebuilder")
        self.assertIn("Portfolio: add a live demo.", [f for x in p["steps"] for f in x["fixes"]])
        md = sync_check.report([{"area": "Headline", "item": "AI Engineer", "surface": "resume", "ok": False, "fix": "Say it."}], [])
        self.assertEqual(scorecard.sync_summary(md)["fixes"], ["Headline (resume): Say it."])
        ok = sync_check.report([{"area": "Headline", "item": "x", "surface": "resume", "ok": True, "fix": ""}], [])
        self.assertTrue(scorecard.sync_summary(ok)["in_sync"])

    def test_step7_rebuild_never_invents(self):
        import resume_rebuild
        brag = self.tmp / "brag"
        brag.mkdir()
        (brag / "2026-10-31.md").write_text("---\nstatus: curated\n---\n## search\n### Cut search latency\n"
                                            "- Impact: 40% faster for 300 users\n- Skills: Redis\n- Portfolio artifact: none\n")
        (brag / "2026-11-01.md").write_text("---\nstatus: raw\n---\n## x\n### Raw item\n- Impact: 9\n")
        record = dict(self.record)
        record["experience"] = [dict(self.record["experience"][0], highlights=["brag/entries/2026-10-31.md#cut-search-latency"])]
        market, vocab = resume_rebuild.load_market(str(self.tmp / "rs.json"))
        r = resume_rebuild.rebuild(record, resume_rebuild.read_brag(str(brag)), market, vocab)
        self.assertIn("- Cut search latency: 40% faster for 300 users", r["resume"])
        self.assertNotIn("Raw item", r["resume"])
        self.assertIn("[ask: email]", r["asks"])
        listed = set(self.record["artifacts"][0]["skills"]) | {"Redis"}
        on = lexicon.find_skills(r["resume"], vocab)
        self.assertTrue(on <= {s for s in on if s in listed or s.lower() in r["resume"].lower()})
        for s in r["prove_first"]:
            self.assertNotIn(s, lexicon.find_skills(r["resume"].split("SKILLS")[1], vocab))
        c = resume_rebuild.check(r["resume"])
        self.assertFalse(c["pass"])  # placeholders and no email yet
        self.assertTrue(resume_rebuild.check(docs.read_text(str(FIX / "screen_resume.txt")))["checks"])

    def test_step7_refuses_out_path_in_git(self):
        import resume_rebuild
        repo = self.tmp / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        rc = resume_rebuild.main(["--portfolio", str(ROOT / "templates" / "portfolio.json"), "--out", str(repo / "r.txt")])
        self.assertEqual(rc, 2)
        self.assertFalse((repo / "r.txt").exists())

    def test_step7_allow_repo_writes_into_a_private_repo(self):
        import resume_rebuild
        repo = self.tmp / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        rc = resume_rebuild.main(["--portfolio", str(ROOT / "templates" / "portfolio.json"),
                                  "--out", str(repo / "r.txt"), "--allow-repo"])
        self.assertEqual(rc, 0)
        self.assertIn("EXPERIENCE", (repo / "r.txt").read_text())


if __name__ == "__main__":
    unittest.main()


class TestDeckM2Decode(unittest.TestCase):
    def test_three_mentions_is_critical(self):
        text = ("Requirements\n- Python services in production\n- Python and SQL\n"
                "Nice to have\n- Python tooling, Kubernetes\n")
        import screen_grade
        q = screen_grade.split_posting("Eng", text)
        d = {x["skill"]: x for x in q["decode"]}
        self.assertTrue(d["Python"]["critical"])
        self.assertEqual(d["Python"]["tier"], "required")
        self.assertFalse(d["Kubernetes"]["critical"])
        self.assertEqual(d["Kubernetes"]["tier"], "preferred")
        self.assertEqual(q["decode"][0]["skill"], "Python")


class TestDeckM7Funnel(unittest.TestCase):
    def _rows(self, f):
        with open(f) as fh:
            return list(csv.DictReader(fh))

    def test_columns_postmortem_and_break_point(self):
        with tempfile.TemporaryDirectory() as td:
            f = str(pathlib.Path(td) / "f.csv")
            funnel.main(["init", "--file", f])
            for i in range(10):
                funnel.main(["add", "--file", f, "--company", f"C{i}", "--role", "Dev", "--source", "job-board",
                             "--next-action", "follow up", "--follow-up", "2000-01-01"])
            funnel.main(["close", "--file", f, "--id", "1", "--status", "rejected"])
            funnel.main(["postmortem", "--file", f, "--id", "1", "--cause", "no AWS proof",
                         "--fix", "AWS bullet with a number", "--layer", "resume"])
            rows = self._rows(f)
            for col in ("next_action", "follow_up", "pm_cause", "pm_fix", "pm_layer"):
                self.assertIn(col, rows[0])
            self.assertEqual(rows[0]["pm_layer"], "resume")
            md = funnel.build_report(rows, None)
            self.assertIn("No screens -> fix the **resume** layer", md)
            self.assertIn("Follow-ups due: 9", md)
            self.assertIn("no AWS proof -> fix: AWS bullet with a number [resume]", md)

    def test_diagnose_layers(self):
        self.assertEqual(funnel.diagnose(12, 0, 0, 0)[1], "resume")
        self.assertEqual(funnel.diagnose(12, 4, 0, 0)[1], "interview")
        self.assertEqual(funnel.diagnose(12, 5, 2, 0)[1], "defense")
        self.assertIsNone(funnel.diagnose(12, 5, 2, 1))

    def test_72_hour_rule(self):
        import datetime as dt
        rows = [{"id": "1", "company": "A", "role": "Dev", "channel": "cold", "stage": "applied",
                 "stage_date": "2026-11-01", "status": "rejected", "date_applied": "2026-11-01",
                 "pm_date": "2026-11-02T09:00:00", "pm_fix": "new headline", "pm_layer": "resume"}]
        md = funnel.build_report(rows, None, at=dt.datetime(2026, 11, 6))
        self.assertIn("no upward movement: it was opinion", md)
        rows.append(dict(rows[0], id="2", stage="screen", stage_date="2026-11-03", pm_fix="", pm_date=""))
        md = funnel.build_report(rows, None, at=dt.datetime(2026, 11, 6))
        self.assertIn("upward movement, keep it", md)


class TestOnetCsvLayout(unittest.TestCase):
    """Release 31.0 dropped the text files: CSV, new file names, new column names."""

    CSV = ("O*NET-SOC Code,Title,Workplace Example,Element ID,Element Name,Hot Technology,In Demand\n"
           "15-1252.00,Software Developers,Python,2.E.7.a,Development software,Y,Y\n"
           '15-1252.00,Software Developers,"Hypertext markup language HTML",2.E.7.a,Web software,Y,Y\n')

    def test_reads_the_csv_columns(self):
        o = onet.Onet(version="31_0")
        o._cache["Technology Skills.txt"] = onet.parse_tsv(self.CSV, delimiter=",")
        ts = o.technology_skills("15-1252.00")
        self.assertEqual([t["skill"] for t in ts], ["Python", "Hypertext markup language HTML"])
        self.assertTrue(ts[0]["hot"] and ts[0]["in_demand"])
        d, vocab = demand.build_demand(ts, [], top=25)
        self.assertEqual({x.skill for x in d}, {"Python", "HTML"})  # a resume that says "HTML" matches

    def test_urls_and_version_follow_the_release(self):
        self.assertTrue(onet._file_url("31_0", "Technology Skills.txt").endswith("db_31_0_csv/software_skills.csv"))
        self.assertTrue(onet._file_url("30_2", "Technology Skills.txt").endswith("db_30_2_text/Technology%20Skills.txt"))
        with mock.patch.object(onet, "fetch", return_value='<a href="/dl_files/database/db_31_0_csv/x.csv">'), \
                mock.patch.dict(onet.os.environ, {}, clear=True):
            self.assertEqual(onet.latest_version(), "31_0")

    def test_ties_at_the_cut_are_kept(self):
        rows = [{"skill": f"Tool{i:02d}", "category": "", "hot": True, "in_demand": True} for i in range(30)]
        d, _ = demand.build_demand(rows, [], top=25)
        self.assertEqual(len(d), 30)  # the alphabet doesn't decide who is in the lane


class TestMatcherAndNumbers(unittest.TestCase):
    def test_plain_english_is_not_a_skill(self):
        v = lexicon.CURATED
        for line in ("Held a Secret security clearance", "Mentored the rest of the team", "Managed 12 insurance agents",
                     "Quick to react under pressure", "Swift delivery of container shipments", "https://github.com/me"):
            self.assertEqual(lexicon.find_skills(line, v), set(), line)
        found = lexicon.find_skills("REST APIs in Go, React and Docker; HTML, CSS, application security", v)
        self.assertTrue({"REST APIs", "Go", "React", "Docker", "HTML", "CSS", "Security"} <= found)

    def test_a_number_is_a_quantity(self):
        for t in ("cut 40%", "10,000 requests", "$2M saved", "3x faster", "p95 under 120 ms"):
            self.assertTrue(lexicon.has_number(t), t)
        for t in ("Stored files in S3", "OAuth2 on EC2", "on call 24/7", "HTML5 and K8s"):
            self.assertFalse(lexicon.has_number(t), t)

    def test_onet_names_get_the_short_alias(self):
        v = lexicon.build_vocab(["Extensible markup language XML2", "Atlassian Confluence", "Oracle PeopleSoft software"])
        self.assertIn("Atlassian Confluence", lexicon.find_skills("Wrote runbooks in Confluence", v))
        self.assertIn("Oracle PeopleSoft software", lexicon.find_skills("PeopleSoft admin", v))


class TestResumeScoreRules(unittest.TestCase):
    RESUME = ("Jane Doe\njane@example.com\n\nExperience\nEngineer, Acme, Jan 2023 - Present\n"
              "- Built a Python service on Kubernetes that cut deploy time\n  by 40% for the whole team\n"
              "- Stored files in S3 using Terraform\n"
              "Developer, Beta, Jun 2019 - Dec 2021\n- Tuned Kafka pipelines, cutting lag by 60%\n\n"
              "Skills\nPython, Docker\n\nEducation\nBS, State U\n" + "filler word " * 80)

    def grades(self, now):
        import resume_score as rs
        import screen_grade as sg
        v = lexicon.build_vocab()
        lines = sg.sections(self.RESUME)
        spans = rs.role_spans(lines, now)
        return {k: rs.grade_skill(k, v, lines, spans, now)[0] for k in ("Python", "Kubernetes", "Terraform", "Apache Kafka", "Docker")}

    def test_wrapped_bullet_digits_in_names_and_stale_by_month(self):
        import datetime as dt
        g = self.grades(dt.date(2026, 11, 10))
        self.assertEqual(g["Python"], "proven")       # the number is on the wrapped second line
        self.assertEqual(g["Kubernetes"], "proven")
        self.assertEqual(g["Terraform"], "applied")   # the 3 in S3 is not a number
        self.assertEqual(g["Docker"], "listed")
        self.assertEqual(g["Apache Kafka"], "proven")  # ended Dec 2021: not yet five years ago
        self.assertEqual(self.grades(dt.date(2027, 1, 15))["Apache Kafka"], "stale")

    def test_score_counts_the_best_n_and_no_phone_still_scores(self):
        import resume_score as rs
        rows = [{"skill": n, "category": "", "hot": True, "in_demand": True} for n in
                ("Python", "Kubernetes", "Terraform", "Java", "C#", "Angular", "Azure", "Go")]
        r = rs.score(self.RESUME, rows, [], now=2026, need=2)
        self.assertIsNotNone(r["score"])               # no phone: a fix on the report, not a block
        self.assertIn("Phone", [c["check"] for c in r["checks"] if not c["pass"]])
        self.assertEqual(r["text_score"], 100)         # two skills proven on paper, two asked for (capped at 100)
        self.assertEqual(r["score"], 80)               # nothing outside backs them yet: 70 measured, plus the calibration
        self.assertEqual(rs.score(self.RESUME, rows, [], now=2026, need=8)["text_score"], 44)  # 34 measured
        self.assertEqual(rs.best_n([(1, 1.0), (1, 0.7), (1, 0)], None), 100 * 1.7 / 3)

    def test_order_is_judged_per_section_and_plural_tests_count(self):
        import screen_grade as sg
        text = docs.read_text(str(FIX / "screen_resume.txt"))  # a 2025 project sits under a 2020 job
        order = [f for f in sg.format_checks(text, sg.sections(text)) if f["rule"].startswith("Reverse")][0]
        self.assertTrue(order["ok"])
        swapped = self.RESUME.replace("Jan 2023 - Present", "Jan 2018 - Dec 2018")
        order = [f for f in sg.format_checks(swapped, sg.sections(swapped)) if f["rule"].startswith("Reverse")][0]
        self.assertFalse(order["ok"])
        v = lexicon.build_vocab()
        self.assertIn("Testing", lexicon.find_skills("runs unit and integration tests on every pull request", v))
        self.assertIn("Testing", lexicon.find_skills("Added automated tests", v))
        self.assertNotIn("Testing", lexicon.find_skills("Ran usability tests with customers", v))

    def test_real_resume_shapes_raise_no_false_flags(self):
        import resume_score as rs
        import screen_grade as sg
        text = ("Jane Doe\njane@example.com\n\nPROFESSIONAL EXPERIENCE\n"
                "Engineer, Acme, April 2026 – Present\n- Built a Python service used by 40 teams\n"
                "Developer, Beta, February 2018 – June 2020\n- Shipped React interfaces\n\n"
                "EARLIER EXPERIENCE\nWeb Developer, Gamma, February 2015 – May 2016\n\n"
                "LEADERSHIP\nFounder, Nonprofit, May 2014 – Present\n- Built the platform in Python for 500 users\n\n"
                "TEACHING & PUBLICATIONS\n- Instructor, Courses Inc (March 2020 – Present)\n- Instructor, Other Co (January 2023 – Present)\n\n"
                "AWARDS, CERTIFICATIONS & SERVICE\n- Google I/O 2025 invitee; Engineer I, Acme\n"
                "- Air Force (September 2004 – September 2009)\n")
        lines = sg.sections(text)
        self.assertEqual({s for s, _ in lines}, {"header", "experience", "leadership", "teaching & publications",
                                                 "awards, certifications & service"})
        fmt = {f["rule"].split()[0]: f["ok"] for f in sg.format_checks(text, lines)}
        self.assertTrue(fmt["No"])        # the I in "Google I/O" and "Engineer I" is not a pronoun
        self.assertTrue(fmt["Reverse"])   # two roles that both run to Present are in order
        self.assertTrue(sg.PRONOUN.search("Then I led the team") and sg.PRONOUN.search("I've shipped it"))
        gaps = [c["detail"] for c in rs.chronology(text, 2026) if c["flag"].startswith("Gap")]
        self.assertEqual(len(gaps), 1)    # 2009 to 2014 is a gap; 2016 to 2018 is covered by the 2014 - Present role
        self.assertIn("2009", gaps[0])
        spans = rs.role_spans(lines, 2026)  # a Leadership role with a number counts as experience
        self.assertEqual(rs.grade_skill("Python", lexicon.build_vocab(), lines, spans, 2026)[0], "proven")

    def test_role_search_prefers_the_occupation_that_names_the_role(self):
        o = onet.Onet(version="30_2")
        o._cache["Occupation Data.txt"] = [{"O*NET-SOC Code": c, "Title": t} for c, t in (
            ("17-2051.00", "Civil Engineers"), ("17-2141.00", "Mechanical Engineers"), ("15-1254.00", "Web Developers"),
            ("15-1221.00", "Computer and Information Research Scientists"), ("15-1252.00", "Software Developers"))]
        o._cache["Alternate Titles.txt"] = [{"O*NET-SOC Code": c, "Alternate Title": t, "Short Title": ""} for c, t in (
            ("15-1221.00", "AI Engineer (Artificial Intelligence Engineer)"), ("15-1254.00", "Back End Engineer"),
            *[("17-2051.00", f"Civil Engineer {i}") for i in range(40)], ("17-2141.00", "Aircraft Maintenance Engineer"))]
        top = lambda q: o.search(q, limit=1)[0]["code"]
        self.assertEqual(top("AI engineer"), "15-1221.00")       # not the occupation with the most "engineer" titles
        self.assertEqual(top("backend engineer"), "15-1254.00")  # "backend" = "Back End"
        self.assertEqual(top("software developer"), "15-1252.00")
        self.assertEqual(o.search("zzzqqq"), [])

    def test_bad_input_is_refused_before_any_pull(self):
        import resume_score as rs
        with tempfile.TemporaryDirectory() as d:
            resume = pathlib.Path(d) / "r.txt"
            resume.write_text(self.RESUME)
            base = ["--resume", str(resume), "--onet", "15-1252.00"]
            with mock.patch.object(rs.onet_mod, "Onet", side_effect=AssertionError("pulled before checking input")):
                self.assertEqual(rs.main(base + ["--github", str(pathlib.Path(d) / "missing.json")]), 2)
                self.assertEqual(rs.main(base + ["--postings", str(pathlib.Path(d) / "nodir")]), 2)
                self.assertEqual(rs.main(base + ["--md", str(ROOT / "leak.md")]), 2)  # the report quotes the resume
                with self.assertRaises(SystemExit):
                    rs.main(base + ["--need", "0"])

    def test_allow_repo_scores_inside_a_private_repo(self):
        import resume_score as rs
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            resume = pathlib.Path(d) / "r.txt"
            resume.write_text(self.RESUME)
            base = ["--resume", str(resume), "--onet", "15-1252.00", "--md", str(pathlib.Path(d) / "score.md")]
            offline = mock.patch.object(rs.onet_mod, "Onet", side_effect=rs.FetchError("offline"))
            with offline:
                self.assertEqual(rs.main(base), 2)                   # refused before any pull
                self.assertEqual(rs.main(base + ["--allow-repo"]), 3)  # let through: stops at the offline pull
        self.assertFalse((ROOT / "leak.md").exists())

    def test_every_surface_score_carries_the_calibration(self):
        import github_score
        import linkedin_score
        import portfolio_audit
        from jobdata import calibration as cal
        self.assertEqual((cal.calibrate(0), cal.calibrate(55.4), cal.calibrate(95), cal.calibrate(100)), (10, 65, 100, 100))
        half = [{"section": "s", "check": "a", "pass": True, "weight": 1, "detail": ""},
                {"section": "s", "check": "b", "pass": False, "weight": 1, "detail": ""}]
        self.assertEqual(portfolio_audit.score(half), 60)  # 50 measured
        self.assertIn("60 / 100", portfolio_audit.summarize(half))
        self.assertIn("10-point calibration", portfolio_audit.summarize(half))
        mkt = {"skills": [("Python", 1.0)], "vocab": lexicon.build_vocab(), "source": "test"}
        li = linkedin_score.score("Headline: Dev\n", mkt)
        self.assertEqual(li["score"], cal.calibrate(linkedin_score.mk.weighted(li["checks"])))
        self.assertEqual(li["calibration"], 10)
        self.assertIn("10-point calibration", linkedin_score.report_md(li))
        self.assertTrue(hasattr(github_score, "cal"))
        gated = {"surface": "resume", "score": None, "verdict": "No score", "parse_gate": []}  # no score stays no score
        import resume_score as rs
        self.assertIsNone(rs.corroborate(dict(gated))["score"])

    def test_gate_reads_the_resume_alone(self):
        import scorecard
        r = {"surface": "resume", "score": 65, "text_score": 90, "checks": [], "skills": []}
        self.assertTrue(scorecard.composite({"resume": r})["gate"]["passed"])


class TestScreenGradeFixes(unittest.TestCase):
    def setUp(self):
        import screen_grade
        self.sg = screen_grade
        self.quals = screen_grade.split_posting("Software Engineer", (FIX / "screen_posting.txt").read_text())
        self.resume = str(FIX / "screen_resume.txt")

    def grades(self, quotes):
        return {"grades": [{"id": q["id"], "met": q["id"] in quotes, "evidence": quotes.get(q["id"], "")}
                           for q in self.quals["basic"] + self.quals["preferred"]]}

    def test_html_posting_keeps_its_lines(self):
        html = ("<p>About us</p><h3>Requirements</h3><ul><li>5+ years of Python</li><li>Experience with AWS</li></ul>"
                "<h3>Nice to have</h3><ul><li>Kubernetes</li></ul>")
        q = self.sg.split_posting("Software Engineer", postings.html_to_text(html))
        self.assertEqual((len(q["basic"]), len(q["preferred"])), (2, 1))
        curly = self.sg.split_posting("Eng", "What you\u2019ll bring\n- Python in production\n- SQL\n")
        self.assertEqual(len(curly["basic"]), 2)  # job boards write the apostrophe curly

    def test_an_empty_quote_is_not_a_quote(self):
        text = (FIX / "screen_resume.txt").read_text()
        for quote in ("", "...", " ... ", "a"):
            self.assertFalse(self.sg.quote_found(quote, text), quote)

    def test_refuses_a_quote_that_names_the_wrong_skill(self):
        r = self.sg.grade(self.resume, self.quals, self.grades({"B4": "Designed PostgreSQL schemas and SQL reports used by 12 analysts"}), None)
        self.assertTrue(any("B4" in m and "CI/CD" in m for m in r["refused"]))
        ok = self.sg.grade(self.resume, self.quals, self.grades({"B4": "Wrote the GitHub Actions CI/CD pipeline"}), None)
        self.assertNotIn("refused", ok)

    def test_two_graders_agreement(self):
        a = self.grades({q["id"]: "x" for q in self.quals["basic"]})
        b = self.grades({q["id"]: "x" for q in self.quals["basic"][:-1]})
        same = self.sg.agreement(self.quals, a, a)
        self.assertTrue(same["ok"] and same["agreement"] == 1.0)
        diff = self.sg.agreement(self.quals, a, b)
        self.assertEqual(diff["letters"], ["B", "C"])
        self.assertEqual(diff["differ"], [self.quals["basic"][-1]["id"]])
        self.assertFalse(diff["ok"])

    def test_composite_reports_the_screen_grade(self):
        import scorecard
        g = self.sg.grade(self.resume, self.quals, self.grades({"B2": "Designed PostgreSQL schemas and SQL reports used by 12 analysts"}), None)
        c = scorecard.composite({"linkedin": {"surface": "linkedin", "score": 80, "checks": []}},
                                screens=[scorecard.screen_summary(g, "screen.json")])
        self.assertEqual(c["screens"][0]["grade"], "D")
        self.assertTrue(c["screens"][0]["flag"])
        self.assertIn("Screen Grade", scorecard.composite_md(c))
        self.assertTrue(scorecard.plan(c)["screen_fixes"])
        with self.assertRaises(ValueError):
            scorecard.screen_summary({"surface": "resume"}, "x.json")


class TestLinkedInParsing(unittest.TestCase):
    def test_a_sentence_is_not_a_heading(self):
        import linkedin_score
        s = linkedin_score.split_profile("Headline: Dev\nAbout:\nI build APIs.\nExperience with Kubernetes is my strength.\n"
                                         "Skills I use daily include Python.\nExperience:\nDev, Co, 2024 - Present\n")
        self.assertIn("Experience with Kubernetes", s["about"])
        self.assertEqual(s["experience"], "Dev, Co, 2024 - Present")
        self.assertNotIn("skills", s)

    def test_pdf_reading_order_and_skipped_checks(self):
        import linkedin_score
        from jobdata import market
        pdf = ("Contact\njane@example.com\nwww.linkedin.com/in/jane (LinkedIn)\nTop Skills\nPython\nFastAPI\n"
               "Certifications\nAWS Certified Developer\nJane Doe\nSoftware Developer · Python, FastAPI\n"
               "Atlanta, Georgia, United States\nSummary\nI build services.\nExperience\nExample Co\nSoftware Developer\n"
               "January 2024 - Present\nCut latency 40% with Redis\nPage 1 of 2\nEducation\nExample University\n")
        s = linkedin_score.split_profile(pdf)
        self.assertEqual(s["headline"], "Software Developer · Python, FastAPI")
        self.assertEqual(s["location"], "Atlanta, Georgia, United States")
        self.assertEqual(s["certifications"], "AWS Certified Developer")
        self.assertNotIn("Page 1", s["experience"])
        mkt = {"skills": [("Python", 1.0)], "vocab": lexicon.build_vocab(), "source": "test"}
        names = lambda r: {c["check"] for c in r["checks"]}
        from_pdf = linkedin_score.score(pdf, mkt, from_pdf=True)
        self.assertEqual(from_pdf["skipped"][:2], ["Featured", "Open to Work"])
        self.assertNotIn("Featured has links", names(from_pdf))
        self.assertNotIn("Skills section covers the lane's top 10", names(from_pdf))  # the PDF shows only the top skills
        self.assertIn("Featured has links", names(linkedin_score.score(pdf, mkt)))


    def test_pdf_layout_splits_the_sidebar_and_joins_a_wrapped_headline(self):
        import linkedin_score
        pad = lambda left, right: f"{left:<39}{right}"
        layout = "\n".join([
            "Contact", "jane@example.com", pad("", "Jane Doe"),
            pad("", "Software Developer | Python, FastAPI | 300+ users,"), pad("www.linkedin.com/in/", "94% uptime | Backend"),
            pad("jane (LinkedIn)", "Atlanta, Georgia, United States"), "", "Top Skills", pad("", "Summary"),
            pad("Python", "I build services."), pad("FastAPI", ""), pad("", "Experience"), pad("Certifications", "Example Co"),
            pad("AWS Certified Developer", "Software Developer"), pad("", "January 2024 - Present"),
            pad("", "Page 1 of 2"), "\fCut latency 40% with Redis", "Education", "Example University"])
        s = linkedin_score.split_profile(linkedin_score.pdf_columns(layout))
        self.assertEqual(s["headline"], "Software Developer | Python, FastAPI | 300+ users, 94% uptime | Backend")
        self.assertEqual(s["location"], "Atlanta, Georgia, United States")
        self.assertEqual(s["skills"], "Python\nFastAPI")
        self.assertEqual(s["certifications"], "AWS Certified Developer")  # the sidebar stays out of Experience
        self.assertEqual(s["experience"], "Example Co\nSoftware Developer\nJanuary 2024 - Present\nCut latency 40% with Redis")


class TestPortfolioAudit(unittest.TestCase):
    def test_client_rendered_site_is_named_not_failed_wholesale(self):
        import portfolio_audit
        spa = '<html lang="en"><head><title>Jane Doe</title></head><body><div id="root"></div><script src="/app.js"></script></body></html>'
        with mock.patch.object(portfolio_audit, "fetch", return_value=spa):
            res, notes = portfolio_audit.audit_site("https://jane.dev")
        by = {c["check"]: c["pass"] for c in res}
        self.assertFalse(by["Content is in the HTML, readable without JavaScript"])
        self.assertNotIn("Links to GitHub", by)
        self.assertTrue(notes)

    def test_site_is_checked_against_the_record_and_script_text_is_ignored(self):
        import portfolio_audit
        page = ('<html lang="en"><head><title>Jane Doe</title><script>var tests = "ci/cd";</script></head><body><h1>Jane, developer</h1>'
                + "<p>" + "I build backend services for logistics teams. " * 10 + "</p>"
                '<p>See my testimonials.</p><a href="https://github.com/jane">GitHub</a></body></html>')

        def fake(url, **kw):
            if "robots" in url or "sitemap" in url or "dead" in url:
                raise portfolio_audit.FetchError("404")
            return page

        record = {"artifacts": [{"name": "rag-eval-harness", "depth": 3, "url": "https://jane.dev/dead"},
                                {"name": "local-toy", "depth": 1}]}
        with mock.patch.object(portfolio_audit, "fetch", side_effect=fake):
            res, _ = portfolio_audit.audit_site("https://jane.dev", record)
        by = {c["check"]: c["pass"] for c in res}
        self.assertFalse(by["Mentions tests, CI or evals"])  # "testimonials" and inline script text don't count
        self.assertFalse(by["rag-eval-harness is on the site"])
        self.assertFalse(by["rag-eval-harness: live link loads"])
        self.assertNotIn("local-toy is on the site", by)

    def test_artifact_pages_writing_and_a_contact_page_count(self):
        import portfolio_audit
        home = ('<html lang="en"><head><title>Jane Doe</title></head><body><h1>Jane, developer</h1>'
                + "<p>" + "I build backend services for logistics teams. " * 10 + "</p>"
                '<a href="/artifacts/rag-eval-harness/">Deep dive</a><a href="/artifacts/pricing-api/#eval">Deep dive</a>'
                '<a href="/writing/">Writing</a><a href="/contact/">Contact</a></body></html>')
        with mock.patch.object(portfolio_audit, "fetch", return_value=home):
            res, _ = portfolio_audit.audit_site("https://jane.dev")
        by = {c["check"]: c["pass"] for c in res}
        self.assertTrue(by["Has project or case-study pages"])
        self.assertTrue(by["Links to writing, talks or press"])
        self.assertTrue(by["Contact path (email, form or contact page)"])

    def test_checklist_items_need_a_quote(self):
        import portfolio_audit
        ok = portfolio_audit.checklist_checks([{"section": "First Impression", "item": "Says what you build", "pass": True,
                                                "quote": "I build backend services"}])
        self.assertTrue(ok[0]["pass"])
        with self.assertRaises(ValueError):
            portfolio_audit.checklist_checks([{"section": "First Impression", "item": "Says what you build", "pass": True}])


class TestScoreAll(unittest.TestCase):
    """score_all.py: the chain in one command. The steps are stubbed; each is tested on its own above."""

    def setUp(self):
        import score_all
        self.sa = score_all
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.calls: list[tuple[str, list[str]]] = []

    def _step(self, surface, rc=0, score=70):
        def main(argv):
            self.calls.append((surface, argv))
            if not rc:
                pathlib.Path(argv[argv.index("--json") + 1]).write_text(json.dumps(
                    {"surface": surface, "score": score, "checks": [], "skill_evidence": {}}))
            return rc
        return main

    def _run(self, argv, **rcs):
        sa = self.sa
        with mock.patch.object(sa.resume_score, "main", self._step("resume", rcs.get("resume", 0))), \
                mock.patch.object(sa.linkedin_score, "main", self._step("linkedin", rcs.get("linkedin", 0))), \
                mock.patch.object(sa.github_score, "main", self._step("github", rcs.get("github", 0))), \
                mock.patch.object(sa.portfolio_audit, "main", self._step("portfolio", rcs.get("portfolio", 0))), \
                mock.patch.object(sa.resume_score, "corroborate", side_effect=lambda r, _: r), \
                mock.patch.object(sa.resume_score, "report_md", return_value="resume report"):
            return sa.main(["--dir", str(self.tmp), *argv])

    def test_one_command_runs_the_chain_and_remembers_the_answers(self):
        first = ["--resume", "me.pdf", "--role", "software developer", "--linkedin", "Profile.pdf",
                 "--github", "me", "--repos", "a,org/b", "--url", "https://me.dev"]
        self.assertEqual(self._run(first), 0)
        self.assertEqual([c[0] for c in self.calls], ["resume", "linkedin", "github", "portfolio"])
        total = json.loads((self.tmp / "composite.json").read_text())["total"]
        self.assertEqual((total["score"], total["out_of"]), (280, 400))
        self.assertTrue((self.tmp / "plan.md").exists())
        self.calls.clear()
        self.assertEqual(self._run([]), 0)  # no flags the second time
        self.assertEqual([c[0] for c in self.calls], ["resume", "linkedin", "github", "portfolio"])
        self.assertIn("a,org/b", dict(self.calls)["github"])

    def test_a_surface_that_fails_is_left_out_not_read_from_an_old_file(self):
        (self.tmp / "github-score.json").write_text(json.dumps({"surface": "github", "score": 99, "checks": []}))
        rc = self._run(["--resume", "me.pdf", "--onet", "15-1252.00", "--github", "me"], github=3)
        self.assertEqual(rc, 3)
        total = json.loads((self.tmp / "composite.json").read_text())["total"]
        self.assertEqual((total["score"], total["out_of"]), (70, 100))

    def test_stops_when_the_resume_cant_be_scored(self):
        self.assertEqual(self._run(["--resume", "me.pdf", "--role", "x", "--github", "me"], resume=3), 3)
        self.assertEqual([c[0] for c in self.calls], ["resume"])
        self.assertFalse((self.tmp / "composite.json").exists())

    def test_refuses_a_folder_in_git_and_a_first_run_without_a_resume(self):
        self.assertEqual(self._run([]), 2)
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        self.assertEqual(self._run(["--resume", "me.pdf", "--role", "x"]), 2)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.tmp / "score-all.json").exists())

    def test_allow_repo_runs_in_a_private_repo_and_is_remembered(self):
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        self.assertEqual(self._run(["--resume", "me.pdf", "--onet", "15-1252.00", "--allow-repo"]), 0)
        self.assertIn("--allow-repo", dict(self.calls)["resume"])
        self.calls.clear()
        self.assertEqual(self._run([]), 0)  # no flags the second time
        self.assertEqual([c[0] for c in self.calls], ["resume"])
