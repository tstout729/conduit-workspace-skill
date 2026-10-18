"""Offline checks for the conduit-workspace scripts. Usage: python3 -I -B tests/test_scripts.py [SKILL_DIR]"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

SKILL = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "conduit-workspace")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SKILL, "scripts", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


snap = load("conduit_snapshot")
lint = load("conduit_lint")
failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


class Fake(snap.Client):
    def __init__(self, pages):
        super().__init__("x", 0)
        self.pages = list(pages)

    def request(self, method, path, query=None, body=None):
        return self.pages.pop(0)


for label, pages in {
    "repeated cursor raises": [{"data": [1], "has_more": True, "next_cursor": "a"},
                               {"data": [2], "has_more": True, "next_cursor": "a"}],
    "missing cursor raises": [{"data": [1], "has_more": True, "next_cursor": None}],
    "missing data list raises": [{"items": []}],
}.items():
    try:
        Fake(pages).paged("/v1/skills", {})
        check(label, False)
    except snap.IncompleteExport:
        check(label, True)

ok = Fake([{"data": [1], "has_more": True, "next_cursor": "a"}, {"data": [2], "has_more": False}]).paged("/x", {})
check("normal pagination returns all items", ok == [1, 2])

try:
    snap.kb_inventory(Fake([{"data": [{"id": 1}], "has_more": False, "total_count": 5}]), "w", False)
    check("kb count mismatch raises", False)
except snap.IncompleteExport:
    check("kb count mismatch raises", True)

with tempfile.TemporaryDirectory() as d:
    open(os.path.join(d, "old.json"), "w").close()
    env = {**os.environ, "CONDUIT_API_TOKEN": "fake"}
    r = subprocess.run([sys.executable, "-I", os.path.join(SKILL, "scripts", "conduit_snapshot.py"), "--out", d],
                       capture_output=True, text=True, env=env)
    check("refuses non-empty output folder", r.returncode == 2 and "not empty" in r.stderr)

secret_line = "Gate keypad code is 482913 for the side door."  # check:allow (fabricated)
token_line = 'const api_key = "zzzzfabricatedvalue1234567";'  # check:allow (fabricated)
f = lint.Findings(10)
lint.scan_text(f, "a", "guardrail: x", secret_line + " Say you can make a brief natural admission of uncertainty.")
lint.scan_text(f, "a", "tool", token_line, is_code=True)
out = json.dumps(f.items)
check("credential finding reported", any(i["check"] == "credential-like-text" for i in f.items))
check("hardcoded secret reported", any(i["check"] == "hardcoded-secret" for i in f.items))
check("no secret digits in output", "482913" not in out and "4829" not in out)
check("no secret text in output", "zzzzfab" not in out)
f2 = lint.Findings(10)
lint.scan_text(f2, "a", "persona", "Network Elkhorn, key bluespruceforest. A brief natural admission of uncertainty helps.")
out2 = json.dumps(f2.items)
check("uncertainty reported as policy", any(i["severity"] == "policy" for i in f2.items))
check("no alphabetic password near uncertainty", "bluespruce" not in out2 and "Elkhorn" not in out2)
err = snap.ApiError(500, "/v1/agents?workspace_id=w", '{"error":"leaked-sensitive-zzz"}')
check("api error string carries no response body", "leaked-sensitive" not in str(err) and "workspace_id" not in str(err))
try:
    Fake([{"data": [1], "next_cursor": "a"}]).paged("/v1/agents", {})
    check("missing has_more raises", False)
except snap.IncompleteExport:
    check("missing has_more raises", True)
check("email domain not a mention", set(lint.mentions("write to ops@example.com")) == set())
check("sentence-final mention kept whole", set(lint.mentions("Call @get-stay-quote.")) == {"get-stay-quote"})
check("known one-word tool is a mention", set(lint.mentions("Use @lookup now.", frozenset({"lookup"}))) == {"lookup"})
check("unknown one-word handle ignored", set(lint.mentions("ask @frontdesk")) == set())

try:
    snap.kb_inventory(Fake([{"data": [], "has_more": False, "total_count": "leaky-total-zzz"}]), "w", False)
    check("non-integer total_count raises", False)
except snap.IncompleteExport as e:
    check("non-integer total_count raises without echo", "leaky-total" not in str(e))

with tempfile.TemporaryDirectory() as d:
    agents = [{"id": "a1", "name": "A", "instructions": "Wi-Fi is @purple-otter-river-77 for guests. Use @get-stay-quote.",
               "skill_ids": [], "guardrails": []}]
    json.dump(agents, open(os.path.join(d, "agents.json"), "w"))
    json.dump([], open(os.path.join(d, "skills.json"), "w"))
    json.dump([{"name": "get-stay-quote", "description": "x" * 100}], open(os.path.join(d, "custom-tools.json"), "w"))
    r = subprocess.run([sys.executable, "-I", os.path.join(SKILL, "scripts", "conduit_lint.py"), d],
                       capture_output=True, text=True)
    check("lint runs end to end", r.returncode == 0)
    check("unknown @token never printed", "purple-otter" not in r.stdout + r.stderr)
    check("known unusable tool named", "@get-stay-quote names a tool" in r.stdout)

with tempfile.TemporaryDirectory() as d:
    def put(rel, obj):
        os.makedirs(os.path.dirname(os.path.join(d, rel)) or d, exist_ok=True)
        raw = json.dumps(obj).encode()
        open(os.path.join(d, rel), "wb").write(raw)
        import hashlib
        return hashlib.sha256(raw).hexdigest()
    files = {"agents.json": put("agents.json", [{"id": "a1", "name": "A"}]),
             "skills.json": put("skills.json", []),
             "custom-tools.json": put("custom-tools.json", [])}
    json.dump({"complete": True, "files": files}, open(os.path.join(d, "manifest.json"), "w"))
    fl = lint.Findings(10)
    lint.verify_manifest(d, json.load(open(os.path.join(d, "manifest.json"))), [{"id": "a1"}], fl)
    check("missing per-agent exports flagged", sum(i["check"] == "damaged-snapshot" for i in fl.items) == 2)
    open(os.path.join(d, "skills.json"), "w").write("[1]")
    fl = lint.Findings(10)
    lint.verify_manifest(d, json.load(open(os.path.join(d, "manifest.json"))), [], fl)
    check("altered file flagged", any("changed" in i["detail"] for i in fl.items))

check("retry-after seconds", snap.retry_delay("7") == 7.0)
check("retry-after http date", 0.0 <= snap.retry_delay("Wed, 21 Oct 2015 07:28:00 GMT") <= 120.0)
check("retry-after garbage falls back", snap.retry_delay("leaky-header-zzz") == 10.0)
check("retry-after missing falls back", snap.retry_delay(None) == 10.0)

with tempfile.TemporaryDirectory() as d:
    agents = [{"id": "a1", "name": "A", "instructions": "", "skill_ids": [], "guardrails": [],
               "operation_mode": "leaky-mode-zzz", "enabled": "leaky-enabled-zzz"}]
    json.dump(agents, open(os.path.join(d, "agents.json"), "w"))
    json.dump([], open(os.path.join(d, "skills.json"), "w"))
    os.makedirs(os.path.join(d, "agent-connections"))
    json.dump([{"provider": "slack", "status": "leaky-status-zzz", "enabled_tool_names": ["x"]}],
              open(os.path.join(d, "agent-connections", "a1.json"), "w"))
    json.dump([{"title": "t", "source": "leaky-source-zzz", "entity_ids": ["l1"]}], open(os.path.join(d, "kb-nodes.json"), "w"))
    r = subprocess.run([sys.executable, "-I", "-B", os.path.join(SKILL, "scripts", "conduit_lint.py"), d],
                       capture_output=True, text=True)
    check("malformed enums not echoed", r.returncode == 0 and "leaky-" not in r.stdout + r.stderr)

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
