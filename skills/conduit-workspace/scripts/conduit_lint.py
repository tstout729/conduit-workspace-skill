#!/usr/bin/env python3
"""Offline checks on a folder written by conduit_snapshot.py.

Finds configuration problems that repeatedly hurt Conduit agents: shared and
global objects, personal or disconnected connections, unresolved @ references,
credential-like text in prompts, oversized guardrails, restated paragraphs,
orphan or disabled skills, and unscoped knowledge. Findings are hints to read
in full, not verdicts.

Examples:
  python3 conduit_lint.py /tmp/conduit-snap
  python3 conduit_lint.py /tmp/conduit-snap --agent "Guest Agent" --max-per-check 50

Prints JSON on stdout. Findings give object names and character offsets,
never the matched value or the prose around it. Severity "policy" marks a
choice the operator may have made on purpose. One-word @names are checked
only when they match a known tool or skill; how Conduit stores other
mention types is undocumented. Exit codes: 0 ran, 2 usage.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

MENTION = re.compile(r"(?<![\w.@])@([a-z][a-z0-9_-]*[a-z0-9])")
# A number of 4-8 digits within a few words of an access word. check:allow
CODE_NEAR = re.compile(
    r"(?i)\b(code|pin|passcode|keypad|lockbox|combo|combination|password|wi-?fi)\b[^\n]{0,40}?(?<![\d:$.,/-])(\d{4,8})(?![\d:]|\s?(?:am|pm)\b)"
)
HARDCODED_SECRET = re.compile(r"(?i)(bearer\s+[a-z0-9._\-]{24,}|(?:api[_-]?key|secret|token)\s*[:=]\s*['\"][^'\"]{16,}['\"])")
UNCERTAINTY = re.compile(
    r"(?i)(admission of uncertainty|admit(?:ting)? (?:that )?(?:you|it|i) (?:don't|do not) know|say (?:plainly )?(?:that )?(?:you're|you are|i'm|i am) not sure)"
)
GUARDRAIL_LIMIT = 3000
PERSONA_LIMIT = 20000
SKILL_BODY_LIMIT = 15000
DESCRIPTION_LIMIT = 1024
PARAGRAPH_MIN = 300


def load(folder, name, default=None):
    path = os.path.join(folder, name)
    if not os.path.exists(path):
        return default
    with open(path) as fh:
        return json.load(fh)


MODES = {"autopilot", "copilot", "inactive"}
STATUSES = {"connected", "disconnected", "error", "expired", "pending", "revoked"}
SOURCES = {"pms", "manual", "ingest", "link", "notion", "google_drive", "airtable"}


def known(value, allowed):
    """An enum value for output, or a fixed label; never echoes unexpected text."""
    return value if value in allowed else ("missing" if value is None else "unexpected value")


def year_like(value):
    return len(value) == 4 and value.startswith("20")


class Findings:
    def __init__(self, limit):
        self.limit = limit
        self.items = []
        self.counts = Counter()

    def add(self, severity, check, obj, detail, agent=None):
        self.counts[(check, severity)] += 1
        if self.counts[(check, severity)] <= self.limit:
            item = {"severity": severity, "check": check, "object": obj, "detail": detail}
            if agent:
                item["agent"] = agent
            self.items.append(item)


def scan_text(findings, agent, label, text, is_code=False):
    for m in CODE_NEAR.finditer(text):
        if year_like(m.group(2)):
            continue
        findings.add("high", "credential-like-text", label,
                     f"credential-like value after '{m.group(1).lower()}' at character {m.start(2)}; "
                     "inspect the private snapshot", agent)
    if is_code:
        for m in HARDCODED_SECRET.finditer(text):
            findings.add("high", "hardcoded-secret", label,
                         f"secret-like value at character {m.start()}; inspect the private snapshot", agent)
    for m in UNCERTAINTY.finditer(text):
        findings.add("policy", "uncertainty-allowed", label,
                     f"text at character {m.start()} lets the agent tell guests it doesn't know; "
                     "fine only if the operator chose that", agent)


def mentions(text, known=frozenset()):
    """{name: first offset} for @names that look like tool or skill names, or match a known one.

    Skips email domains. Callers print only names found in the known inventory,
    because an unknown @token could be any prompt text, including a password.
    """
    found = {}
    for m in MENTION.finditer(text):
        name, rest = m.group(1), text[m.end():m.end() + 2]
        if re.match(r"\.[a-z]", rest):
            continue
        if "-" in name or "_" in name or name in known:
            found.setdefault(name, m.start())
    return found


def verify_manifest(folder, manifest, agents, findings):
    """Flags a snapshot whose files are missing, altered, or never finished."""
    if os.path.exists(os.path.join(folder, "INCOMPLETE")) or manifest.get("complete") is not True:
        findings.add("high", "incomplete-snapshot", folder,
                     "no complete manifest; findings may miss objects and the folder is not a rollback source")
        return
    files = manifest.get("files") or {}
    required = ["agents.json", "skills.json", "custom-tools.json"]
    for a in agents:
        required += [f"agent-tools/{a['id']}.json", f"agent-connections/{a['id']}.json"]
    for rel in required:
        if rel not in files:
            findings.add("high", "damaged-snapshot", rel, "required export missing from the manifest")
    for rel, digest in files.items():
        path = os.path.join(folder, rel)
        if not os.path.exists(path):
            findings.add("high", "damaged-snapshot", rel, "listed in the manifest but missing")
            continue
        with open(path, "rb") as fh:
            if hashlib.sha256(fh.read()).hexdigest() != digest:
                findings.add("high", "damaged-snapshot", rel, "changed since the snapshot was taken")


def paragraphs(text):
    for part in re.split(r"\n\s*\n", text or ""):
        norm = " ".join(part.split())
        if len(norm) >= PARAGRAPH_MIN:
            yield norm


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("snapshot", help="folder written by conduit_snapshot.py")
    parser.add_argument("--agent", action="append", help="agent name or ID to check (repeatable); default all")
    parser.add_argument("--max-per-check", type=int, default=25, help="cap listed findings per check and severity")
    args = parser.parse_args()

    agents = load(args.snapshot, "agents.json")
    skills = load(args.snapshot, "skills.json")
    tools = load(args.snapshot, "custom-tools.json", [])
    if agents is None or skills is None:
        print("Not a snapshot folder: agents.json or skills.json is missing.", file=sys.stderr)
        return 2

    findings = Findings(args.max_per_check)
    verify_manifest(args.snapshot, load(args.snapshot, "manifest.json") or {}, agents, findings)
    skill_by_id = {s["id"]: s for s in skills}
    names = {a["id"]: a.get("name") or a["id"] for a in agents}
    wanted = set(args.agent or [])
    checked = [a for a in agents if not wanted or a["id"] in wanted or a.get("name") in wanted]
    if wanted and not checked:
        print("No agent matched --agent.", file=sys.stderr)
        return 2

    consumers = defaultdict(list)
    for a in agents:
        for sid in a.get("skill_ids") or []:
            consumers[sid].append(names[a["id"]])

    # Workspace-level objects.
    for sid, users in consumers.items():
        if len(users) > 1:
            label = skill_by_id.get(sid, {}).get("name", sid)
            findings.add("medium", "shared-skill", label, "attached to: " + ", ".join(sorted(users)))
    for s in skills:
        if s["id"] not in consumers:
            findings.add("info", "orphan-skill", s.get("name"), "attached to no agent")
        desc = s.get("description") or ""
        if len(desc) > DESCRIPTION_LIMIT:
            findings.add("high", "description-too-long", s.get("name"), f"{len(desc)} chars")
        elif len(desc) < 80:
            findings.add("info", "description-vague", s.get("name"), f"{len(desc)} chars; may not win selection")
    for t in tools:
        if t.get("enable_globally"):
            findings.add("medium", "global-tool", t.get("name"), "enabled for every agent, including protected ones")
        if len(t.get("description") or "") > DESCRIPTION_LIMIT:
            findings.add("high", "description-too-long", t.get("name"), f"{len(t['description'])} chars")
        scan_text(findings, None, f"custom tool {t.get('name')}", (t.get("code") or ""), is_code=True)

    # Agent-level checks.
    summaries = []
    for a in checked:
        agent = names[a["id"]]
        mode = known(a.get("operation_mode"), MODES)
        enabled = a.get("enabled") if isinstance(a.get("enabled"), bool) else "unexpected value"
        if enabled and mode == "inactive":
            findings.add("info", "mode-vs-enabled", agent, "enabled is true but operation_mode is inactive", agent)

        access = load(args.snapshot, f"agent-tools/{a['id']}.json", [])
        enabled_tools = {t["name"] for t in access if t.get("enabled")}
        all_tools = {t["name"] for t in access} | {t.get("name") for t in tools}
        global_tools = {t.get("name") for t in tools if t.get("enable_globally")}
        known_names = frozenset(all_tools | {s.get("name") for s in skills})
        conns = load(args.snapshot, f"agent-connections/{a['id']}.json", [])
        conn_tools = set()
        for c in conns:
            label = f"connection: {c.get('display_name') or c.get('provider')}"
            if c.get("status") != "connected":
                findings.add("medium", "connection-not-connected", label,
                             f"status {known(c.get('status'), STATUSES)}; its tools look enabled but can't run", agent)
            else:
                conn_tools.update(c.get("enabled_tool_names") or [])
            if c.get("scope") == "user" and c.get("enabled_tool_names"):
                findings.add("medium", "personal-connection", label,
                             f"user-scoped with {len(c['enabled_tool_names'])} tools; runs on that person's "
                             "credentials for every conversation", agent)

        attached = []
        for sid in a.get("skill_ids") or []:
            s = skill_by_id.get(sid)
            if not s:
                findings.add("medium", "missing-skill", sid, "in skill_ids but not in the skills list", agent)
                continue
            if not s.get("enabled", True):
                findings.add("medium", "disabled-skill-attached", s.get("name"), "attached but disabled", agent)
            attached.append(s)
        skill_names = {s.get("name") for s in attached}

        stack = [("persona", a.get("instructions") or "")]
        for g in a.get("guardrails") or []:
            body = g.get("knowledge") or ""
            stack.append((f"guardrail: {g.get('title')}", body))
            if len(body) > GUARDRAIL_LIMIT:
                findings.add("medium", "oversized-guardrail", g.get("title"),
                             f"{len(body)} chars; a procedure here belongs in a Conduit skill", agent)
        for s in attached:
            stack.append((f"skill: {s.get('name')}", s.get("body") or ""))
            if len(s.get("body") or "") > SKILL_BODY_LIMIT:
                findings.add("info", "large-skill", s.get("name"), f"{len(s['body'])} chars", agent)
        if len(a.get("instructions") or "") > PERSONA_LIMIT:
            findings.add("info", "large-persona", agent, f"{len(a['instructions'])} chars", agent)

        para_owners = defaultdict(set)
        for label, text in stack:
            scan_text(findings, agent, label, text)
            for ref, offset in mentions(text, known_names).items():
                if ref in skill_names or ref in enabled_tools or ref in global_tools or ref in conn_tools:
                    continue
                if ref in known_names:
                    detail = f"@{ref} names a tool or skill this agent can't use"
                else:
                    detail = (f"@-mention at character {offset} matches no known tool or skill "
                              "(it may be a workflow, listing or status mention); read it in the snapshot")
                findings.add("medium", "unresolved-reference", label, detail, agent)
            for p in paragraphs(text):
                para_owners[p].add(label)
        repeats = sorted(((len(o), p, o) for p, o in para_owners.items() if len(o) > 1), reverse=True)
        for count, para, owners in repeats:
            pid = hashlib.sha256(para.encode()).hexdigest()[:10]
            findings.add("info", "restated-paragraph", f"paragraph {pid} ({len(para)} chars)",
                         f"same text in {count} objects: " + "; ".join(sorted(owners)[:5]), agent)

        summaries.append({
            "agent": agent, "mode": mode, "enabled": enabled, "model": a.get("model"),
            "persona_chars": len(a.get("instructions") or ""),
            "guardrails": len(a.get("guardrails") or []), "skills": len(attached),
            "tools_enabled": len(enabled_tools), "connection_tools": len(conn_tools),
        })

    nodes = load(args.snapshot, "kb-nodes.json")
    kb = None
    if nodes is not None:
        content = [n for n in nodes if not n.get("is_directory")]
        unscoped = [n for n in content if n.get("enabled", True) and not n.get("entity_ids")]
        for n in unscoped:
            findings.add("info", "kb-workspace-wide", n.get("title"), "no entity scope; reaches every listing's search")
        for n in content:
            if n.get("embed_status") == "failed":
                findings.add("medium", "kb-embed-failed", n.get("title"), "not searchable")
        per_entity = Counter(e for n in content for e in (n.get("entity_ids") or []))
        kb = {
            "content_nodes": len(content), "workspace_wide": len(unscoped),
            "disabled": sum(1 for n in content if n.get("enabled") is False),
            "by_source": dict(Counter(known(n.get("source"), SOURCES) for n in content)),
            "entities": len(per_entity),
            "entities_with_one_node": sum(1 for c in per_entity.values() if c == 1),
        }

    totals = Counter()
    for (check, severity), n in findings.counts.items():
        totals[f"{severity}:{check}"] = n
    print(json.dumps({
        "snapshot": os.path.abspath(args.snapshot),
        "agents": summaries,
        "knowledge": kb,
        "totals": dict(sorted(totals.items())),
        "findings": findings.items,
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
