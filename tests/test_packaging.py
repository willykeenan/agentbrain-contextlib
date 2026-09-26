"""Packaging, docs, and sample-library checks.

Parses SPEC front-matter with the standard library only. Does not import
agentbrain_contextlib.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples" / "sample-library"
PROJECT = SAMPLE / "projects" / "lighthouse-app"

TYPES = (
    "decision",
    "requirement",
    "fact",
    "lesson",
    "glossary",
    "source",
    "return",
    "brief-note",
)
STATUSES = ("proposed", "current", "superseded", "retired")
PREFIX = {
    "decision": "dec",
    "requirement": "req",
    "fact": "fact",
    "lesson": "les",
    "glossary": "glo",
    "source": "src",
    "return": "ret",
    "brief-note": "note",
}
TYPE_DIR = {
    "decision": "decisions",
    "requirement": "requirements",
    "fact": "facts",
    "lesson": "lessons",
    "glossary": "glossary",
    "source": "sources",
    "return": "returns",
    "brief-note": "notes",
}
ID_RE = re.compile(r"^(dec|req|fact|les|glo|src|ret|note)-(\d{8})-([0-9a-f]{4})$")
FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_([a-z0-9-]+)_([0-9a-f]{4})\.md$")
HOME_PATH_RE = re.compile(
    r"(?:/Users/|/home/|/root/|C:\\Users\\|C:/Users/)",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{8,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|"
    r"api[_-]?key\s*[:=]\s*\S+)",
    re.IGNORECASE,
)
REQUIRED_META = (
    "id",
    "type",
    "title",
    "status",
    "project",
    "created",
    "author",
    "evidence",
    "supersedes",
    "superseded_by",
    "review_by",
    "tags",
    "sensitivity",
    "body_sha256",
)
REQUIRED_DOCS = (
    "README.md",
    "pyproject.toml",
    "docs/QUICKSTART.md",
    "docs/MCP.md",
    "docs/SSD.md",
    "docs/SPEC.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "LICENSE",
    ".github/workflows/ci.yml",
    "examples/sample-library/README.md",
    "examples/sample-library/INDEX.md",
    "examples/sample-library/library.json",
    "examples/sample-library/projects/lighthouse-app/README.md",
    "examples/sample-library/projects/lighthouse-app/BRIEF.md",
    "examples/sample-library/projects/lighthouse-app/INDEX.md",
    "examples/sample-library/projects/lighthouse-app/project.json",
)


def _strip_comment(line: str) -> str:
    in_str = False
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if in_str:
            if quote == '"' and c == "\\" and i + 1 < len(line):
                i += 2
                continue
            if c == quote:
                in_str = False
                quote = None
            i += 1
            continue
        if c in "\"'":
            in_str = True
            quote = c
            i += 1
            continue
        if c == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i].rstrip()
        i += 1
    return line.rstrip()


def _skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t":
        i += 1
    return i


def _parse_quoted(s: str, i: int):
    q = s[i]
    i += 1
    out = []
    while i < len(s):
        c = s[i]
        if q == '"' and c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            mapping = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"'}
            out.append(mapping.get(n, n))
            i += 2
            continue
        if q == "'" and c == "'" and i + 1 < len(s) and s[i + 1] == "'":
            out.append("'")
            i += 2
            continue
        if c == q:
            return "".join(out), i + 1
        out.append(c)
        i += 1
    raise ValueError("unterminated string")


def _coerce_atom(tok: str):
    if tok == "null":
        return None
    if tok == "true":
        return True
    if tok == "false":
        return False
    return tok


def _parse_inline_list_at(s: str, i: int):
    if s[i] != "[":
        raise ValueError("not a list")
    i += 1
    i = _skip_ws(s, i)
    items = []
    if i < len(s) and s[i] == "]":
        return items, i + 1
    while i < len(s):
        i = _skip_ws(s, i)
        if s[i] in "\"'":
            val, i = _parse_quoted(s, i)
        elif s[i] == "{":
            val, i = _parse_inline_map_at(s, i)
        elif s[i] == "[":
            val, i = _parse_inline_list_at(s, i)
        else:
            start = i
            while i < len(s) and s[i] not in ",]":
                i += 1
            val = _coerce_atom(s[start:i].strip())
        items.append(val)
        i = _skip_ws(s, i)
        if i < len(s) and s[i] == ",":
            i += 1
            continue
        if i < len(s) and s[i] == "]":
            return items, i + 1
        raise ValueError("expected , or ] in list")
    raise ValueError("unterminated list")


def _parse_inline_map_at(s: str, i: int):
    if s[i] != "{":
        raise ValueError("not a map")
    i += 1
    i = _skip_ws(s, i)
    out = {}
    if i < len(s) and s[i] == "}":
        return out, i + 1
    while i < len(s):
        i = _skip_ws(s, i)
        if s[i] in "\"'":
            key, i = _parse_quoted(s, i)
        else:
            m = re.match(r"[A-Za-z0-9_]+", s[i:])
            if not m:
                raise ValueError("bad map key")
            key = m.group(0)
            i += len(key)
        i = _skip_ws(s, i)
        if i >= len(s) or s[i] != ":":
            raise ValueError("expected : in map")
        i += 1
        i = _skip_ws(s, i)
        if s[i] in "\"'":
            val, i = _parse_quoted(s, i)
        elif s[i] == "{":
            raise ValueError("nested maps are not allowed")
        elif s[i] == "[":
            val, i = _parse_inline_list_at(s, i)
        else:
            start = i
            while i < len(s) and s[i] not in ",}":
                i += 1
            val = _coerce_atom(s[start:i].strip())
        out[key] = val
        i = _skip_ws(s, i)
        if i < len(s) and s[i] == ",":
            i += 1
            continue
        if i < len(s) and s[i] == "}":
            return out, i + 1
        raise ValueError("expected , or } in map")
    raise ValueError("unterminated map")


def parse_scalar(val: str):
    val = val.strip()
    if val == "null":
        return None
    if val == "true":
        return True
    if val == "false":
        return False
    if val.startswith("["):
        items, end = _parse_inline_list_at(val, 0)
        if val[end:].strip():
            raise ValueError("trailing junk after list")
        return items
    if val.startswith("{"):
        mp, end = _parse_inline_map_at(val, 0)
        if val[end:].strip():
            raise ValueError("trailing junk after map")
        return mp
    if val.startswith('"') or val.startswith("'"):
        s, end = _parse_quoted(val, 0)
        if val[end:].strip():
            raise ValueError("trailing junk after string")
        return s
    return val


def parse_front_matter(block: str) -> dict:
    lines = block.split("\n")
    i = 0
    out = {}
    while i < len(lines):
        raw = lines[i]
        i += 1
        if not raw.strip():
            continue
        if raw.lstrip().startswith("#"):
            continue
        line = _strip_comment(raw)
        if not line.strip():
            continue
        if line.startswith(" ") or line.startswith("\t"):
            raise ValueError("unexpected indent: " + raw)
        if ":" not in line:
            raise ValueError("expected key: " + raw)
        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest == "":
            items = []
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip() or nxt.lstrip().startswith("#"):
                    i += 1
                    continue
                stripped = _strip_comment(nxt)
                if not (stripped.startswith(" ") or stripped.startswith("\t")):
                    break
                item = stripped.strip()
                if item.startswith("- "):
                    items.append(parse_scalar(item[2:].strip()))
                    i += 1
                elif item == "-":
                    items.append(None)
                    i += 1
                else:
                    break
            out[key] = items
        else:
            out[key] = parse_scalar(rest)
    return out


def parse_record(text: str) -> dict:
    if not text.startswith("---"):
        raise ValueError("missing opening ---")
    rest = text[3:]
    if rest.startswith("\n"):
        rest = rest[1:]
    marker = "\n---"
    end = rest.find(marker)
    if end < 0:
        raise ValueError("missing closing ---")
    fm = rest[:end]
    after = rest[end + len(marker) :]
    if after.startswith("\n"):
        body = after[1:]
    else:
        body = after
    return {"meta": parse_front_matter(fm), "body": body}


def valid_evidence_ref(ref: str) -> bool:
    if not isinstance(ref, str) or ":" not in ref:
        return False
    kind, _, value = ref.partition(":")
    if not value:
        return False
    if kind in ("project", "ssd"):
        if value.startswith("/") or value.startswith("~"):
            return False
        if re.match(r"^[A-Za-z]:[\\/]", value):
            return False
        return ".." not in Path(value).parts
    if kind == "url":
        return value.startswith("https://")
    if kind == "room":
        return "#" in value and value.split("#", 1)[1] != ""
    if kind == "note":
        return True
    return False


def iter_record_files(root: Path):
    skip_names = {
        "README.md",
        "INDEX.md",
        "BRIEF.md",
        "GLOSSARY.md",
        "TIMELINE.md",
    }
    for path in sorted(root.rglob("*.md")):
        if path.name in skip_names:
            continue
        text = path.read_text(encoding="utf-8")
        if text.startswith("---"):
            yield path, text


def load_records():
    records = []
    for path, text in iter_record_files(SAMPLE):
        parsed = parse_record(text)
        records.append((path, parsed))
    return records


class TestDoesNotImportPackage(unittest.TestCase):
    def test_this_module_has_no_package_import(self):
        src = Path(__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        pkg = "agentbrain_" + "contextlib"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(
                        alias.name == pkg or alias.name.startswith(pkg + ".")
                    )
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertFalse(mod == pkg or mod.startswith(pkg + "."))

    def test_package_not_loaded(self):
        loaded = [
            k
            for k in sys.modules
            if k == "agentbrain_contextlib" or k.startswith("agentbrain_contextlib.")
        ]
        self.assertEqual(loaded, [])


class TestPyproject(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    def test_exists_and_utf8(self):
        self.assertTrue((ROOT / "pyproject.toml").is_file())
        self.assertTrue(self.text)

    def test_name(self):
        self.assertIn('name = "agentbrain-contextlib"', self.text)

    def test_requires_python_39(self):
        self.assertIn('requires-python = ">=3.9"', self.text)

    def test_license_apache(self):
        self.assertIn("Apache-2.0", self.text)

    def test_console_script(self):
        self.assertIn("ctxlib", self.text)
        self.assertIn("agentbrain_contextlib.cli:main", self.text)
        self.assertRegex(
            self.text,
            r'ctxlib\s*=\s*"agentbrain_contextlib\.cli:main"',
        )

    def test_scripts_table(self):
        self.assertIn("[project.scripts]", self.text)

    def test_src_layout(self):
        self.assertIn('package-dir = {"" = "src"}', self.text)
        self.assertIn('where = ["src"]', self.text)

    def test_no_runtime_dependencies(self):
        self.assertIn("dependencies = []", self.text)

    def test_ke_studios(self):
        self.assertIn("KE Studios", self.text)


class TestDocsPresent(unittest.TestCase):
    def test_required_files_nonempty(self):
        missing = []
        empty = []
        for rel in REQUIRED_DOCS:
            path = ROOT / rel
            if not path.is_file():
                missing.append(rel)
                continue
            if path.stat().st_size == 0:
                empty.append(rel)
        self.assertEqual(missing, [])
        self.assertEqual(empty, [])

    def test_readme_is_front_door(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("ctxlib", text)
        self.assertIn("context_", text)
        self.assertIn("Claude Code", text)
        self.assertIn("Codex", text)
        self.assertIn("Cursor", text)
        self.assertIn(
            "ContextLib is the open library layer of AgentBrain (agentrooms.io).",
            text,
        )
        self.assertIn("agentbrain_contextlib", text)
        self.assertIn("MCP", text)

    def test_ssd_covers_finder_unplugged_macs_index(self):
        text = (ROOT / "docs" / "SSD.md").read_text(encoding="utf-8")
        self.assertIn("README", text)
        self.assertIn("BRIEF", text)
        self.assertIn("decisions/INDEX.md", text)
        self.assertIn("unplugged", text.lower())
        self.assertIn("ctxlib sync", text)
        self.assertIn("library.json", text)
        self.assertIn("index", text.lower())

    def test_quickstart_and_mcp(self):
        quick = (ROOT / "docs" / "QUICKSTART.md").read_text(encoding="utf-8")
        mcp = (ROOT / "docs" / "MCP.md").read_text(encoding="utf-8")
        self.assertIn("ctxlib init", quick)
        self.assertIn("ctxlib mcp --identity", mcp)
        self.assertIn("2024-11-05", mcp)
        self.assertIn("2025-03-26", mcp)
        self.assertIn("2025-06-18", mcp)
        for tool in (
            "context_brief",
            "context_search",
            "context_get",
            "context_record",
            "context_supersede",
            "context_review_due",
            "context_review",
            "context_capture",
            "context_export",
            "context_import",
            "context_status",
        ):
            self.assertIn(tool, mcp)

    def test_ci_matrix(self):
        text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        for version in ("3.9", "3.10", "3.11", "3.12", "3.13"):
            self.assertIn(version, text)
        self.assertIn("ubuntu-latest", text)
        self.assertIn("macos-latest", text)


class TestSampleLibrary(unittest.TestCase):
    def test_library_json(self):
        data = json.loads((SAMPLE / "library.json").read_text(encoding="utf-8"))
        self.assertEqual(data["format"], "contextlib/1")
        self.assertIn("library_id", data)
        self.assertIn("created", data)
        self.assertRegex(
            data["library_id"],
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        )

    def test_project_json(self):
        data = json.loads((PROJECT / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(data["slug"], "lighthouse-app")
        self.assertIn("name", data)
        self.assertIn("purpose", data)
        self.assertIn("created", data)
        self.assertIsInstance(data["owners"], list)
        self.assertIn("review_defaults", data)
        defaults = data["review_defaults"]
        self.assertEqual(defaults["fact"], 30)
        self.assertEqual(defaults["source"], 90)
        self.assertEqual(defaults["decision"], 180)
        self.assertEqual(defaults["lesson"], 365)
        self.assertEqual(defaults["glossary"], 365)
        self.assertIsNone(defaults["requirement"])
        self.assertIsNone(defaults["return"])
        self.assertEqual(defaults["brief-note"], 30)

    def test_brief_size(self):
        brief = (PROJECT / "BRIEF.md").read_bytes()
        self.assertGreater(len(brief), 0)
        self.assertLessEqual(len(brief), 8192)

    def test_handwritten_indexes(self):
        for rel in (
            SAMPLE / "INDEX.md",
            PROJECT / "INDEX.md",
            PROJECT / "README.md",
            PROJECT / "GLOSSARY.md",
            PROJECT / "TIMELINE.md",
        ):
            self.assertTrue(rel.is_file(), rel)
            self.assertGreater(rel.stat().st_size, 0)

    def test_type_indexes(self):
        for folder in TYPE_DIR.values():
            idx = PROJECT / folder / "INDEX.md"
            self.assertTrue(idx.is_file(), idx)
            text = idx.read_text(encoding="utf-8")
            self.assertIn("Current", text)
            self.assertIn("Superseded", text)


class TestSampleRecords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = load_records()

    def test_about_twelve_records(self):
        n = len(self.records)
        self.assertGreaterEqual(n, 10)
        self.assertLessEqual(n, 16)

    def test_every_type_present(self):
        seen = {parsed["meta"]["type"] for _, parsed in self.records}
        self.assertEqual(set(TYPES), seen)

    def test_project_is_lighthouse_app(self):
        for path, parsed in self.records:
            self.assertEqual(
                parsed["meta"]["project"],
                "lighthouse-app",
                path,
            )

    def test_every_record_parses_and_matches_spec(self):
        problems = []
        for path, parsed in self.records:
            meta = parsed["meta"]
            body = parsed["body"]
            for key in REQUIRED_META:
                if key not in meta:
                    problems.append("%s missing %s" % (path.name, key))
            rtype = meta.get("type")
            status = meta.get("status")
            rid = meta.get("id")
            if rtype not in TYPES:
                problems.append("%s bad type %r" % (path.name, rtype))
            if status not in STATUSES:
                problems.append("%s bad status %r" % (path.name, status))
            if not isinstance(rid, str) or not ID_RE.match(rid):
                problems.append("%s bad id %r" % (path.name, rid))
            else:
                prefix, ymd, suffix = ID_RE.match(rid).groups()
                if rtype in PREFIX and PREFIX[rtype] != prefix:
                    problems.append("%s prefix %s != type %s" % (path.name, prefix, rtype))
                match = FILE_RE.match(path.name)
                if not match:
                    problems.append("%s filename does not match SPEC pattern" % path.name)
                else:
                    date_s, _slug, file_suffix = match.groups()
                    if file_suffix != suffix:
                        problems.append("%s suffix mismatch" % path.name)
                    if date_s.replace("-", "") != ymd:
                        problems.append("%s date mismatch id vs filename" % path.name)
                folder = TYPE_DIR.get(rtype)
                if folder and folder not in path.parts:
                    problems.append("%s not under %s/" % (path.name, folder))
                if status == "superseded" and "superseded" not in path.parts:
                    problems.append("%s superseded but not in superseded/" % path.name)
            created = meta.get("created")
            if not isinstance(created, str) or not re.match(
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", created
            ):
                problems.append("%s bad created %r" % (path.name, created))
            sensitivity = meta.get("sensitivity")
            if sensitivity not in ("normal", "private"):
                problems.append("%s bad sensitivity %r" % (path.name, sensitivity))
            tags = meta.get("tags")
            if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
                problems.append("%s tags must be a list of scalars" % path.name)
            supersedes = meta.get("supersedes")
            if not isinstance(supersedes, list):
                problems.append("%s supersedes must be a list" % path.name)
            evidence = meta.get("evidence")
            if not isinstance(evidence, list):
                problems.append("%s evidence must be a list" % path.name)
            else:
                for item in evidence:
                    if not isinstance(item, dict) or "ref" not in item:
                        problems.append("%s evidence item not a flat map with ref" % path.name)
                        continue
                    if not valid_evidence_ref(item["ref"]):
                        problems.append("%s bad evidence ref %r" % (path.name, item["ref"]))
                    extra = set(item) - {"ref", "sha256"}
                    if extra:
                        problems.append("%s evidence extra keys %s" % (path.name, extra))
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
            got = meta.get("body_sha256")
            if got != digest:
                problems.append(
                    "%s body_sha256 mismatch got %s want %s" % (path.name, got, digest)
                )
            if status == "current" and not evidence:
                problems.append("%s current record has no evidence" % path.name)
            needs_review = rtype in (
                "fact",
                "source",
                "decision",
                "lesson",
                "glossary",
                "brief-note",
            )
            if status == "current" and needs_review and meta.get("review_by") in (None, ""):
                problems.append("%s current %s missing review_by" % (path.name, rtype))
            if "scope" in meta and meta["scope"] is not None:
                if not isinstance(meta["scope"], dict):
                    problems.append("%s scope must be a flat map" % path.name)
        self.assertEqual(problems, [])

    def test_bodies_are_markdown(self):
        for path, parsed in self.records:
            self.assertTrue(parsed["body"].strip(), path)
            self.assertNotIn("---", parsed["body"].split("\n", 1)[0])


class TestNoPrivateData(unittest.TestCase):
    SKIP_DIRS = {".git", ".venv", "build", "dist", "__pycache__", ".egg-info"}

    def test_owned_tree_has_no_home_paths_emails_or_tokens(self):
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if any(part in self.SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
                continue
            if path.suffix not in {
                ".md",
                ".yml",
                ".yaml",
                ".toml",
                ".py",
                ".json",
                ".txt",
                "",
            } and path.name not in {"LICENSE", "ci.yml"}:
                if path.suffix not in {".md", ".yml", ".yaml", ".toml", ".py", ".json"}:
                    continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            rel = path.relative_to(ROOT).as_posix()
            if path.resolve() == Path(__file__).resolve():
                continue
            if HOME_PATH_RE.search(text):
                hits.append("home-path:" + rel)
            if EMAIL_RE.search(text) and path.name != "LICENSE":
                hits.append("email:" + rel)
            if SECRET_RE.search(text):
                hits.append("secret:" + rel)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
