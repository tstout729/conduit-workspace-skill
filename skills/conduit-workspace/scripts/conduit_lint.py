#!/usr/bin/env python3
"""Offline checks on a folder written by conduit_snapshot.py.

Finds configuration problems that repeatedly hurt Conduit agents: shared and
global objects, personal or disconnected connections, unresolved @ references,
credential-like text in prompts, oversized guardrails, restated paragraphs,
orphan or disabled skills, agents that never run or share an inbox, fixed
reply languages, listing IDs in guardrails, urgent tags, inactive listings,
listings with only their PMS article, duplicate articles and unscoped knowledge.
Findings are hints to read in full, not verdicts.

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
    r"(?i)(admission of uncertainty|admit(?:ting)? (?:that )?(?:you|it|i) (?:don't|do not) know|"
    r"say (?:plainly )?(?:that )?(?:you're|you are|i'm|i am) not sure|"
    r"(?:you|i|we) (?:don't|do not) have (?:that|this|the) information|say so honestly|"
    r"(?:tell|let) (?:the guest|them) (?:know )?(?:that )?(?:you(?:'re| are)|we(?:'re| are)) (?:checking|looking into))"
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
LANGUAGES = {"English", "Original", "Spanish", "French", "German", "Italian", "Polish", "Portuguese", "Hebrew"}
TRIGGER_TYPES = {"message", "webhook", "cron", "event", "mention", "manual"}
CHANNELS = {"airbnb", "booking_com", "sms", "whatsapp", "messenger", "email", "unthreaded_email", "pms", "widget",
            "instagram", "vrbo", "expedia", "helpdesk", "slack", "line_oa", "portal"}
SCOPE_ID = re.compile(r"\b(?:group|unit):[A-Za-z0-9]")
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
                     f"text at character {m.start()} lets the agent tell guests it doesn't know or is checking; "
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


def message_scopes(agent):
    """Scopes of an agent's enabled message triggers: ("all",), ("inbox", id) or ("channel", type)."""
    scopes = set()
    for t in agent.get("triggers") or []:
        if t.get("type") != "message" or not t.get("enabled"):
            continue
        config = t.get("config") or {}
        kind = config.get("scope_type")
        if kind == "inbox":
            scopes.add(("inbox", str(config.get("inbox_type_id"))))
        elif kind == "channel":
            scopes.add(("channel", known(config.get("channel_type"), CHANNELS)))
        else:
            scopes.add(("all",))
    return scopes


def overlap(a, b):
    return bool(a & b) or (("all",) in a and b) or (("all",) in b and a)


def norm_title(title):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (title or "").lower()).split())


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
    names_wanted = {names[a["id"]] for a in checked}
    if wanted and not checked:
        print("No agent matched --agent.", file=sys.stderr)
        return 2

    listings = load(args.snapshot, "listings.json")
    groups = load(args.snapshot, "listing-groups.json") or []
    tags = load(args.snapshot, "conversation-tags.json")
    listing_names = {str(l.get("listingId")): l.get("internalName") or l.get("name") or str(l.get("listingId"))
                     for l in listings or [] if l.get("listingId")}
    # Conduit listing refs (knowledge scope) map to PMS listing IDs only through listing groups.
    ref_to_id, ref_active = {}, {}
    for g in groups:
        for m in g.get("listings") or []:
            if m.get("listingRef"):
                ref_to_id[str(m["listingRef"])] = str(m.get("listingId"))
                ref_active[str(m["listingRef"])] = m.get("isActive")
    id_to_ref = {v: k for k, v in ref_to_id.items()}
    nodes = load(args.snapshot, "kb-nodes.json")
    pms_title = {}
    for n in nodes or []:
        if n.get("source") == "pms":
            for e in n.get("entity_ids") or []:
                pms_title.setdefault(str(e), n.get("title"))
    for ref, title in pms_title.items():
        listing_names.setdefault(ref, title or ref)
    for ref, lid in ref_to_id.items():
        listing_names.setdefault(ref, listing_names.get(lid, ref))
    # Long IDs only: a short numeric PMS ID could match digits inside a phone number or code.
    listing_ids = [i for i in listing_names if len(i) >= 12]

    # Two live agents listening to the same inbox answer the same guests.
    live = [(names[a["id"]], message_scopes(a)) for a in agents
            if a.get("enabled") is True and known(a.get("operation_mode"), MODES) in ("autopilot", "copilot")]
    # An inbox-scoped and a channel-scoped trigger can still overlap; that pairing isn't checked.
    for i, (n1, s1) in enumerate(live):
        for n2, s2 in live[i + 1:]:
            if s1 and s2 and overlap(s1, s2) and (not wanted or n1 in names_wanted or n2 in names_wanted):
                findings.add("medium", "shared-inbox", f"{n1} / {n2}",
                             "both have enabled message triggers on the same inbox, channel or all messages")

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
        live_triggers = [t for t in a.get("triggers") or [] if t.get("enabled")]
        trigger_types = sorted({known(t.get("type"), TRIGGER_TYPES) for t in live_triggers})
        if enabled is True and mode in ("autopilot", "copilot"):
            if not live_triggers:
                findings.add("medium", "never-runs", agent, f"operation_mode {mode} but no enabled trigger; it never runs", agent)
            elif "message" not in trigger_types:
                findings.add("info", "no-message-trigger", agent,
                             "answers no guest messages; enabled triggers: " + ", ".join(trigger_types), agent)
        language = known(a.get("response_language"), LANGUAGES)
        if a.get("response_language") is not None and language != "Original":
            findings.add("policy", "fixed-reply-language", agent,
                         f"replies in {language} whatever language the guest writes", agent)

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
            named = sorted({listing_names[i] for i in listing_ids if i in body})
            if named or SCOPE_ID.search(body):
                findings.add("medium", "listing-id-in-guardrail", g.get("title"),
                             (f"names {len(named)} listing(s), first: {named[0]}; " if named else "holds a group: or unit: ID; ")
                             + "guardrails load for every listing; put listing rules in scoped knowledge or a skill, "
                             "and stop an agent for a listing with routing or listing state", agent)
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
            for name in sorted(n for n in known_names if n and ("-" in n or "_" in n) and len(n) >= 6):
                if name in skill_names or name in enabled_tools or name in global_tools or name in conn_tools:
                    continue
                if re.search(r"(?<![\w@-])" + re.escape(name) + r"(?![\w-])", text):
                    findings.add("medium", "unavailable-tool-named", label,
                                 f"names {name} without @, but this agent can't use it", agent)
            for p in paragraphs(text):
                para_owners[p].add(label)
        repeats = sorted(((len(o), p, o) for p, o in para_owners.items() if len(o) > 1), reverse=True)
        for count, para, owners in repeats:
            pid = hashlib.sha256(para.encode()).hexdigest()[:10]
            findings.add("info", "restated-paragraph", f"paragraph {pid} ({len(para)} chars)",
                         f"same text in {count} objects: " + "; ".join(sorted(owners)[:5]), agent)

        summaries.append({
            "agent": agent, "mode": mode, "enabled": enabled, "model": a.get("model"),
            "response_language": language, "triggers": trigger_types,
            "autopilot_schedule": bool(a.get("autopilot_schedule")),
            "reply_delay_ms": a.get("custom_response_delay_ms") if isinstance(a.get("custom_response_delay_ms"), int) else None,
            "persona_chars": len(a.get("instructions") or ""),
            "guardrails": len(a.get("guardrails") or []), "skills": len(attached),
            "tools_enabled": len(enabled_tools), "connection_tools": len(conn_tools),
        })

    for t in tags or []:
        if t.get("urgency_level") == "urgent":
            count = t.get("count") if isinstance(t.get("count"), int) else "unknown"
            findings.add("info", "urgent-tag", t.get("name"),
                         f"stops the AI on every conversation it tags (count: {count}); confirm a person should own these")
    inactive = [l for l in listings or [] if l.get("isActive") is False or l.get("active") is False]
    if inactive:
        sample = ", ".join(sorted(listing_names.get(str(l.get("listingId")), "listing") for l in inactive)[:10])
        findings.add("info", "inactive-listings", f"{len(inactive)} listings",
                     f"inactive in Conduit, so no agent runs for their guests; confirm that is intended (first: {sample})")
    active_by_name = {}
    for l in listings or []:
        for k in ("internalName", "name", "publicName"):
            if l.get(k):
                active_by_name[l[k]] = not (l.get("isActive") is False or l.get("active") is False)

    kb = None
    if nodes is not None:
        content = [n for n in nodes if not n.get("is_directory")]
        unscoped = [n for n in content if n.get("enabled", True) and not n.get("entity_ids")]
        for n in unscoped:
            findings.add("info", "kb-workspace-wide", n.get("title"), "no entity scope; reaches every listing's search")
        for n in content:
            if n.get("embed_status") == "failed":
                findings.add("medium", "kb-embed-failed", n.get("title"), "not searchable")
        # The same code in many listings' articles may open more than one home (bodies only with --kb-bodies).
        code_listings = defaultdict(set)
        for n in content:
            if n.get("enabled", True) is False:
                continue
            listings_of = {str(e) for e in n.get("entity_ids") or [] if not str(e).startswith("group:")}
            for m in CODE_NEAR.finditer(n.get("body") or ""):
                if not year_like(m.group(2)):
                    code_listings[m.group(2)] |= listings_of
        shared = sorted((len(v), v) for v in code_listings.values() if len(v) >= 3)
        for i, (count, ids) in enumerate(reversed(shared), 1):
            first = ", ".join(sorted(listing_names.get(e, e) for e in ids)[:3])
            findings.add("high", "shared-code-in-knowledge", f"code {i}",
                         f"the same code appears in articles for {count} listings (first: {first}); "
                         "confirm it opens nothing outside each home before any agent serves it")
        seen_titles = Counter((norm_title(n.get("title")), tuple(sorted(n.get("entity_ids") or [])))
                              for n in content if n.get("enabled", True) is not False and n.get("title"))
        for (title, scope), count in seen_titles.items():
            if count > 1 and title:
                findings.add("info", "duplicate-article", title[:80],
                             f"{count} enabled articles with this title and the same scope; two versions of a fact?")
        # A listing is covered by a non-PMS article scoped to it, to one of its units, or to a group it is in.
        covered = set()
        group_members = {str(g.get("groupId")): [str(m.get(k)) for m in g.get("listings") or []
                                                 for k in ("listingRef", "listingId") if m.get(k)] for g in groups}
        for n in content:
            if n.get("enabled", True) is False or n.get("source") == "pms":
                continue
            for e in n.get("entity_ids") or []:
                e = str(e)
                if e.startswith("group:"):
                    targets = group_members.get(e[6:], [])
                elif e.startswith("unit:"):
                    targets = [e.split(":")[1]]
                else:
                    targets = [e]
                for t in targets:
                    covered.update({t, ref_to_id.get(t, t), id_to_ref.get(t, t)})
        for ref, title in pms_title.items():
            active = ref_active.get(ref)
            if active is None:
                active = active_by_name.get(title)
            if ref not in covered and active is not False:
                findings.add("medium", "pms-only-listing", title or ref,
                             "its only knowledge is the PMS article: no property or access facts of its own"
                             + ("" if active else " (active state unknown)"))
        per_entity = Counter(e for n in content for e in (n.get("entity_ids") or []))
        kb = {
            "content_nodes": len(content), "workspace_wide": len(unscoped),
            "disabled": sum(1 for n in content if n.get("enabled") is False),
            "by_source": dict(Counter(known(n.get("source"), SOURCES) for n in content)),
            "entities": len(per_entity),
            "entities_with_one_node": sum(1 for c in per_entity.values() if c == 1),
        }
    listing_summary = None
    if listings is not None:
        listing_summary = {"listings": len(listings), "inactive": len(inactive), "groups": len(groups)}

    totals = Counter()
    for (check, severity), n in findings.counts.items():
        totals[f"{severity}:{check}"] = n
    print(json.dumps({
        "snapshot": os.path.abspath(args.snapshot),
        "agents": summaries,
        "knowledge": kb,
        "listings": listing_summary,
        "not_exported": (load(args.snapshot, "manifest.json") or {}).get("skipped"),
        "totals": dict(sorted(totals.items())),
        "findings": findings.items,
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
