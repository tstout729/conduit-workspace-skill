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

# conduit_failures.py
fail = load("conduit_failures")
from datetime import datetime, timedelta, timezone  # noqa: E402

iso = fail.iso

now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)


def at(hours_ago):
    return (now - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def msg(hours_ago, direction, body, sender="contact", ai=False):
    return {"created_at": at(hours_ago), "direction": direction, "body": body,
            "sender": {"type": sender}, "is_sent_by_autopilot": ai}


check("parse_time handles Z and milliseconds", fail.parse_time("2026-10-10T12:00:00.123Z") == now.replace(microsecond=123000))
check("parse_time handles epoch ms", fail.parse_time(1_760_097_600_000).year == 2025)
check("parse_time rejects junk", fail.parse_time("leaky-zzz") is None and fail.parse_time(True) is None)
thread = [msg(50, "inbound", "Where do we park?"),
          msg(49.9, "outbound", "I'll check with the team and let you know!", "agent", True),
          msg(30, "inbound", "Still no answer about parking, any update??"),
          msg(29, "outbound", "Driveway, left side.", "user")]
sig = fail.signals(thread, now, 24)
check("follow-up after AI reply flagged", "guest_followed_up" in sig)
check("teammate after AI flagged", "teammate_after_ai" in sig)
check("kept promise not flagged", "unkept_promise" not in sig)
quiet = [msg(60, "inbound", "Is there a crib?"), msg(59, "outbound", "I'll ask and get back to you.", "agent", True)]
check("unkept promise flagged", "unkept_promise" in fail.signals(quiet, now, 24))
check("last guest question unanswered flagged", "unanswered" in fail.signals([msg(5, "inbound", "hello, is anyone there?")], now, 24))
check("closing thanks not unanswered", "unanswered" not in fail.signals([msg(5, "inbound", "Thanks so much!")], now, 24))
check("fresh guest message not yet unanswered", "unanswered" not in fail.signals([msg(1, "inbound", "hello")], now, 24))
check("happy thread has no signals", fail.signals([msg(10, "inbound", "Wifi?"), msg(9.9, "outbound", "Elkhorn.", "agent", True),
                                                   msg(9, "inbound", "Thanks!")], now, 24) == set())
check("api send is not a teammate", fail.signals([msg(10, "outbound", "Reminder", "external")], now, 24) == set())
check("low score flagged", fail.score_signals({"support_service_quality_score": 2}) == {"low_score"})
check("bool score ignored", fail.score_signals({"support_service_quality_score": True}) == set())
check("thanks again is not a follow-up", "guest_followed_up" not in fail.signals(
    [msg(10, "outbound", "Towels are in the closet.", "agent", True), msg(9, "inbound", "Thanks again!")], now, 24))
check("directions are not a promise", "unkept_promise" not in fail.signals(
    [msg(60, "outbound", "On the way in, turn left at the gate.", "agent", True)], now, 24))
check("operator automation sends not teammates", fail.signals(
    [{"created_at": at(10), "direction": "outbound", "body": "Check-in details are ready", "sender": {"type": "user", "user_id": "bot1"}}],
    now, 24, automated=frozenset({"bot1"})) == set())
check("copilot teammate sends not flagged", fail.signals([msg(10, "outbound", "Sure!", "user")], now, 24, copilot=True) == set())
check("stay score is its own signal", fail.score_signals({"stay_quality_score": 1}) == {"low_stay_score"})
check("0-1 scale score not treated as low", fail.score_signals({"support_service_quality_score": 0.4}) == set())
check("run not sent flagged", "run_not_sent" in fail.run_signals({"disposition": "resolved", "autopilot_sent": False}))
check("copilot edit flagged", fail.run_signals({"disposition": "resolved", "proposal_outcome": "edited"}) == {"proposal_edited"})
check("approved resolved run is clean", fail.run_signals({"disposition": "resolved", "autopilot_sent": True,
                                                           "proposal_outcome": "approved"}) == set())
old_day, new_day = "2020-01-01T00:00:00Z", iso(datetime.now(timezone.utc))
since = datetime.now(timezone.utc) - timedelta(days=1)
items, cut = fail.in_window(Fake([{"data": [{"created_at": new_day}], "has_more": True, "next_cursor": "a"},
                                  {"data": [{"created_at": old_day}], "has_more": True, "next_cursor": "b"}]), "/x", {}, since, 5)
check("in_window stops at an old page and isn't capped", len(items) == 1 and cut is False)
items, cut = fail.in_window(Fake([{"data": [{"created_at": new_day}], "has_more": True, "next_cursor": "a"},
                                  {"data": [{"created_at": new_day}], "has_more": True, "next_cursor": "b"}]), "/x", {}, since, 2)
check("in_window reports a cap that cut the window", len(items) == 2 and cut is True)
items, cut = fail.in_window(Fake([{"data": [{"created_at": new_day}], "has_more": True, "next_cursor": "a"},
                                  {"data": [{"created_at": new_day}], "has_more": False}]), "/x", {}, since, 2)
check("in_window list ending at the cap isn't capped", cut is False)
items, cut = fail.in_window(Fake([{"data": [{"created_at": old_day}, {"created_at": new_day}], "has_more": True, "next_cursor": "a"},
                                  {"data": [{"created_at": new_day}], "has_more": False}]), "/x", {}, since, 5)
check("in_window reads on when a list isn't newest first", len(items) == 2)
check("call after message flagged", fail.called_after([msg(10, "inbound", "x")], [{"direction": "inbound", "started_at": at(9)}], 24, now))


class FakeApi(snap.Client):
    """Answers by route; records every path and query it was asked for."""

    def __init__(self, routes):
        super().__init__("x", 0)
        self.routes, self.asked = routes, []

    def request(self, method, path, query=None, body=None):
        self.asked.append((method, path, dict(query or {})))
        for prefix, answer in self.routes:
            if path.startswith(prefix):
                return answer(query or {}) if callable(answer) else answer
        raise snap.ApiError(404, path, "")


recent = datetime.now(timezone.utc) - timedelta(days=2)
secret_body = "Gate code 482913, guest Jane Doe +1 503 555 0100 asked again??"  # check:allow (fabricated)
routes = [
    ("/v1/workspaces/w1/settings", {"data": {"timezone": "America/Los_Angeles"}}),
    ("/v1/workspaces", {"data": [{"id": "w1", "name": "W"}]}),
    ("/v1/agents/a1/runs", {"data": [
        {"id": "r1", "contact_id": "c1", "disposition": "escalated", "status": "completed", "created_at": iso(recent)},
        {"id": "r2", "contact_id": "c2", "disposition": "resolved", "status": "completed", "created_at": iso(recent)},
        {"id": "r3", "disposition": "proactive", "status": "completed", "created_at": iso(recent)},
        {"id": "r4", "status": "running", "created_at": iso(recent)},
        {"id": "r0", "contact_id": "c9", "disposition": "escalated", "status": "completed", "created_at": "2020-01-01T00:00:00Z"}],
        "has_more": False}),
    ("/v1/agents", {"data": [{"id": "a1", "name": "Guest Agent", "triggers": [{"type": "message", "enabled": False}]},
                             {"id": "a2", "name": "Notifier", "triggers": [{"type": "cron", "enabled": True}]},
                             {"id": "a3", "name": "Skipped", "triggers": [{"type": "message", "enabled": True}]}], "has_more": False}),
    ("/v1/escalations", lambda q: {"data": [{"id": "e-" + q["status"], "contact_id": "c1", "agent_id": "a1",
                                            "status": q["status"], "created_at": iso(recent),
                                            "guest_message": secret_body, "questions_for_operator": "Parking?"}]
                                   if q["status"] == "resolved" else [], "has_more": False}),
    ("/v1/conversations/lookup", lambda q: {"data": {"conversation": {
        "id": "conv-" + q["contact_id"], "reservation": {"listing_id": "L1", "guest_name": "Jane Doe"},
        "support_service_quality_score": 1, "summary": secret_body}}}),
    ("/v1/conversations/", {"data": [
        {"created_at": iso(recent), "direction": "inbound", "body": secret_body, "sender": {"type": "contact"}},
        {"created_at": iso(recent + timedelta(minutes=1)), "direction": "outbound", "body": "Sure!",
         "sender": {"type": "user"}, "is_sent_by_autopilot": False}], "has_more": False}),
    ("/v1/insights/", {"data": {"numerator": 9, "denominator": 10, "rate": 0.9, "formula_version": "f1"}}),
]
args = type("A", (), dict(workspace=None, days=30, agent=None, all_agents=False, skip_agent=["Skipped"], automated_user=None, sample=5,
                           max_conversations=10, repeat_hours=24,
                           calls=False, max_pages=5))()
api = FakeApi(routes)
with tempfile.TemporaryDirectory() as d:
    out = os.path.join(d, "out")
    os.makedirs(out)
    summary = fail.collect(api, args, out, {})
    cases = json.load(open(os.path.join(out, "cases.json")))
    dumped = json.dumps(summary) + json.dumps(cases)
    check("failures: every escalation status requested",
          {q.get("status") for m, p, q in api.asked if p == "/v1/escalations"} == set(fail.ESCALATION_STATUSES))
    check("failures: only GET requests", all(m == "GET" for m, p, q in api.asked))
    check("failures: run outside the window ignored", all(c["contact_id"] != "c9" for c in cases))
    check("failures: escalated conversation becomes a case with signals",
          any(c["contact_id"] == "c1" and "run_escalated" in c["signals"] and "escalation_resolved" in c["signals"]
              and "low_score" in c["signals"] for c in cases))
    check("failures: resolved conversation sampled", any(c["contact_id"] == "c2" for c in cases))
    check("failures: no message text, names, phones or codes in cases or summary",
          not any(x in dumped for x in ("482913", "Jane", "555", "asked again", "Parking?")))
    check("failures: operator questions kept in the private escalations file",
          "Parking?" in open(os.path.join(out, "escalations.json")).read())
    check("failures: runs without a contact counted", summary["runs_without_contact"] == 2)
    check("failures: notifier agent skipped by default", not any(p.startswith("/v1/agents/a2") for m, p, q in api.asked))
    check("failures: summary serializes with a run that has no disposition", json.dumps(summary, sort_keys=True) is not None)
    check("failures: skipped agent not read", not any(p.startswith("/v1/agents/a3") for m, p, q in api.asked))
    check("failures: rate dates use the workspace timezone", summary["window"]["timezone"] == "America/Los_Angeles")
    check("failures: outbound sender types counted", summary["outbound_by_sender_type"].get("user", 0) >= 1)
    check("failures: repeated user texts counted, not printed", isinstance(summary["repeated_user_texts"], int))

day1, day2 = datetime.now(timezone.utc) - timedelta(days=3), datetime.now(timezone.utc) - timedelta(days=5)
spread_routes = [r for r in routes if not r[0].startswith(("/v1/agents", "/v1/escalations"))] + [
    ("/v1/agents/a1/runs", {"data": [
        {"id": "s1", "contact_id": "d1a", "disposition": "escalated", "status": "completed", "created_at": iso(day1)},
        {"id": "s2", "contact_id": "d1b", "disposition": "escalated", "status": "completed", "created_at": iso(day1 - timedelta(minutes=5))},
        {"id": "s3", "contact_id": "d1c", "disposition": "unresolved", "status": "completed", "created_at": iso(day1 + timedelta(minutes=5))},
        {"id": "s4", "contact_id": "d2a", "disposition": "escalated", "status": "completed", "created_at": iso(day2)}], "has_more": False}),
    ("/v1/agents", {"data": [{"id": "a1", "name": "Guest Agent", "triggers": [{"type": "message"}]}], "has_more": False}),
    ("/v1/escalations", {"data": [], "has_more": False}),
]
spread_args = type("A", (), {**{k: v for k, v in vars(type(args)).items() if not k.startswith("__")}, "max_conversations": 2, "sample": 0})()
with tempfile.TemporaryDirectory() as d:
    fail.collect(FakeApi(spread_routes), spread_args, d, {})
    read = [c["contact_id"] for c in json.load(open(os.path.join(d, "cases.json"))) if not c.get("not_read")]
    check("failures: budget spread across days, escalations before open-for-team runs", sorted(read) == ["d1a", "d2a"])

# conduit_snapshot.py optional exports
skipped = {}
check("optional export skips a missing route", snap.optional("x", lambda: FakeApi([]).request("GET", "/v1/nope"), skipped) is None
      and skipped == {"x": "HTTP 404"})
try:
    snap.camel_paged(Fake([{"data": {"listings": [1], "hasMore": True, "nextCursor": "a"}},
                           {"data": {"listings": [2], "hasMore": True, "nextCursor": "a"}}]), "/x", {}, "listings")
    check("camel pager repeated cursor raises", False)
except snap.IncompleteExport:
    check("camel pager repeated cursor raises", True)
check("camel pager returns all", snap.camel_paged(Fake([{"data": {"listings": [1], "hasMore": True, "nextCursor": "a"}},
                                                        {"data": {"listings": [2], "hasMore": False}}]), "/x", {}, "listings") == [1, 2])

# conduit_lint.py new checks
with tempfile.TemporaryDirectory() as d:
    lid = "a1b2c3d4e5f60718293a4b5c"
    agents = [
        {"id": "a1", "name": "Guest", "enabled": True, "operation_mode": "autopilot", "response_language": "English",
         "instructions": "", "skill_ids": [], "triggers": [{"type": "message", "enabled": True,
                                                           "config": {"scope_type": "inbox", "inbox_type_id": "i1"}}],
         "guardrails": [{"title": "Cabin rule", "knowledge": f"For listing {lid} never mention the hot tub."}]},
        {"id": "a2", "name": "Copy", "enabled": True, "operation_mode": "copilot", "response_language": "Original",
         "instructions": "If the stay is unclear, call search_chat_history first.", "skill_ids": [], "guardrails": [],
         "triggers": [{"type": "message", "enabled": True, "config": {"scope_type": "inbox", "inbox_type_id": "i1"}}]},
        {"id": "a3", "name": "Idle", "enabled": True, "operation_mode": "autopilot", "instructions": "", "skill_ids": [],
         "guardrails": [], "triggers": [{"type": "cron", "enabled": False}]},
    ]
    json.dump(agents, open(os.path.join(d, "agents.json"), "w"))
    json.dump([], open(os.path.join(d, "skills.json"), "w"))
    os.makedirs(os.path.join(d, "agent-tools"))
    json.dump([{"name": "search_chat_history", "enabled": False}], open(os.path.join(d, "agent-tools", "a2.json"), "w"))
    json.dump([{"listingId": lid, "internalName": "Cedar Cabin", "isActive": True},
               {"listingId": "L2xxxxxx", "internalName": "Pine", "isActive": True},
               *[{"listingId": f"L{i}cover0", "internalName": f"Cover {i}", "isActive": True} for i in range(4, 8)],
               {"listingId": "L3xxxxxx", "internalName": "Studio", "isActive": False}], open(os.path.join(d, "listings.json"), "w"))
    json.dump([{"groupId": "g1", "name": "Building", "listings": [{"listingRef": "refBldgA", "listingId": "Lbldg", "isActive": True}]}],
              open(os.path.join(d, "listing-groups.json"), "w"))
    json.dump([{"name": "Refund", "urgency_level": "urgent", "count": 4}], open(os.path.join(d, "conversation-tags.json"), "w"))
    json.dump([{"title": "Pine - parking", "entity_ids": ["L2xxxxxx"]}, {"title": "Pine: Parking", "entity_ids": ["L2xxxxxx"]},
               {"title": "Studio (PMS)", "source": "pms", "entity_ids": ["refStudio"]},
               {"title": "Pine (PMS)", "source": "pms", "entity_ids": ["L2xxxxxx"]},
               {"title": "Bldg A (PMS)", "source": "pms", "entity_ids": ["refBldgA"]},
               {"title": "Building access and Wi-Fi", "entity_ids": ["group:g1"]},
               {"title": "Studio retired (PMS)", "source": "pms", "entity_ids": ["refOld"]},
               *[{"title": f"Cover {i} notes", "entity_ids": [f"L{i}cover0"],
                  "body": "Supply closet keypad code 739184 for the kitchen."} for i in range(4, 8)]],
              open(os.path.join(d, "kb-nodes.json"), "w"))
    r = subprocess.run([sys.executable, "-I", "-B", os.path.join(SKILL, "scripts", "conduit_lint.py"), d],
                       capture_output=True, text=True)
    got = {i["check"] for i in json.loads(r.stdout)["findings"]} if r.returncode == 0 else set()
    for name in ("never-runs", "shared-inbox", "fixed-reply-language", "listing-id-in-guardrail", "urgent-tag",
                 "inactive-listings", "duplicate-article", "pms-only-listing", "unavailable-tool-named"):
        check(f"lint flags {name}", name in got)
    check("pms-only listing named by its article", any(i["check"] == "pms-only-listing" and i["object"] == "Studio (PMS)"
                                                       for i in json.loads(r.stdout)["findings"]))
    check("group-scoped article covers its members", not any(i["check"] == "pms-only-listing" and i["object"] == "Bldg A (PMS)"
                                                              for i in json.loads(r.stdout)["findings"]))
    check("listing with its own article not pms-only", not any(i["check"] == "pms-only-listing" and i["object"] == "Pine (PMS)"
                                                                for i in json.loads(r.stdout)["findings"]))
    check("lint never prints guardrail text", "hot tub" not in r.stdout)
    check("lint flags a code shared across listings", "shared-code-in-knowledge" in got)
    check("lint never prints the shared code", "739184" not in r.stdout)
f3 = lint.Findings(10)
lint.scan_text(f3, "a", "guardrail: x", "If unsure, say you do not have that information yet.")
check("uncertainty check catches 'do not have that information'", any(i["check"] == "uncertainty-allowed" for i in f3.items))

# evals/cases.json, when this checkout has it
cases_path = os.path.join(SKILL, "..", "..", "evals", "cases.json")
if os.path.exists(cases_path):
    ev = json.load(open(cases_path))
    ids = [c.get("id") for c in ev]
    check("eval cases have unique ids", len(ids) == len(set(ids)) and all(ids))
    check("eval cases are complete", all(isinstance(c.get(k), str) and c[k] for c in ev for k in ("id", "mode", "prompt", "context"))
          and all(isinstance(c.get(k), list) and c[k] for c in ev for k in ("expect", "must_not")))

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
