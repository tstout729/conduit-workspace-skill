#!/usr/bin/env python3
"""Read-only collection of the conversations that didn't end the way the operator intended.

Gathers, for a window of days: agent runs that escalated, stayed silent, ended
unresolved or failed; escalations of every status; and, for those
conversations plus a sample of ones the agent resolved, the signals no
disposition shows: a teammate stepping in, the guest writing again with a
follow-up, a guest message left unanswered, a promise nothing followed, a low
Conduit quality score, and (with --calls) a call after messaging. It sends GET
requests only and never changes anything in Conduit.

Examples:
  CONDUIT_API_TOKEN=... python3 conduit_failures.py --out /tmp/conduit-failures
  python3 conduit_failures.py --out cases --days 14 --agent "Guest Agent" --calls

Output files in a new private folder: cases.json (one case per conversation:
IDs, listing, runs, escalations, signals and scores, no message text),
escalations.json (the window's escalations, including the guest message,
proposed reply and Conduit's questions for the operator; private),
rates.json (automation and resolution rate for the window) and manifest.json,
written last with "complete": true. "page_cap_reached" names any list the
--max-pages cap cut short; raise the cap or narrow --days before trusting
totals. Signals are hints to read the thread for, not verdicts. Stdout
carries counts and IDs only.

Exit codes: 0 complete, 2 usage, 3 auth, 4 API or network error, 5 incomplete.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from conduit_snapshot import ApiError, Client, IncompleteExport, write  # noqa: E402

FAILED = {"escalated", "escalation_and_answer", "unresolved", "no_op"}
ESCALATION_STATUSES = ("pending", "reviewed", "resolved", "dismissed")
FOLLOW_UP = re.compile(
    r"(?i)\b(still (no|not|can'?t|cannot|don'?t|doesn'?t|haven'?t|waiting|nothing|broken)|"
    r"(asked|asking|ask) (you )?again|any update|anyone there|didn'?t work|doesn'?t work|not working|"
    r"can'?t find|cannot find|haven'?t heard|no answer|wrong (code|address|house|unit|place|info))\b|\?\s*\?"
)
PROMISE = re.compile(
    r"(?i)(\bi'?ll (check|ask|find out|look into|get back|let you know|follow up|reach out)\b|"
    r"\blet you know\b|\bget back to you\b|\bwill (check|follow up|reach out|be in touch)\b|\bsomeone will\b)"
)
NEEDS_REPLY = re.compile(r"(?i)\?|\b(help|broken|locked out|not working|can'?t|cannot|need|please)\b")
# Conduit's scores were 1-5 integers when observed (October 2026); the spec gives no range.
LOW_SCORE = 2
SERVICE_SCORES = ("customer_sentiment_score", "support_service_quality_score")
SCORES = SERVICE_SCORES + ("stay_quality_score",)
# run_unresolved and run_no_op are often an agent's normal "leave it for the team" outcome, so they rank last.
SEVERE = ("run_failed", "run_escalated", "run_escalation_and_answer", "run_not_sent",
          "escalation_pending", "escalation_reviewed", "escalation_resolved", "escalation_dismissed",
          "proposal_dismissed", "proposal_edited")


def parse_time(value):
    """An aware UTC datetime from an ISO string or epoch number, or None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e12 else value, timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def pages(client, path, query, max_pages):
    """Yield (data list, has_more) per page; raises IncompleteExport on a malformed page or a repeated cursor."""
    cursor, seen = None, set()
    for _ in range(max_pages):
        page = client.request("GET", path, {**query, "cursor": cursor})
        data = page.get("data")
        if not isinstance(data, list) or not isinstance(page.get("has_more"), bool):
            raise IncompleteExport(f"{path.split('?')[0]}: response lacks a data list or a boolean has_more")
        yield data, page["has_more"]
        if not page["has_more"]:
            return
        cursor = page.get("next_cursor")
        if not cursor or cursor in seen:
            raise IncompleteExport(f"{path.split('?')[0]}: has_more is true but the cursor is missing or repeated")
        seen.add(cursor)


def in_window(client, path, query, since, max_pages):
    """(items created since `since`, whether the page cap cut the window short).

    Stops early only while pages arrive newest first; a list in any other order is read to the cap.
    """
    items, ordered, more, last_times = [], True, False, []
    for data, more in pages(client, path, query, max_pages):
        times = [parse_time(i.get("created_at")) for i in data]
        if any(t is None for t in times) or any(a < b for a, b in zip(times, times[1:])):
            ordered = False
        items += [i for i, t in zip(data, times) if t is None or t >= since]
        last_times = times
        if ordered and data and all(t < since for t in times):
            return items, False
    window_open = not last_times or any(t is None or t >= since for t in last_times)
    return items, more and window_open


def signals(messages, now, repeat_hours, copilot=False, automated=frozenset()):
    """Signal names for one conversation's messages (any order). Reads bodies; returns names only.

    With copilot=True, teammate messages are skipped: approved copilot drafts are sent by people.
    Messages from user IDs in `automated` are the operator's own automations, not teammates.
    """
    msgs = sorted(messages, key=lambda m: parse_time(m.get("created_at")) or now)
    found = set()
    window = timedelta(hours=repeat_hours)
    ai_seen = False
    for i, m in enumerate(msgs):
        when = parse_time(m.get("created_at")) or now
        sender = (m.get("sender") or {}).get("type")
        outbound = m.get("direction") == "outbound"
        later = msgs[i + 1:]
        if outbound and m.get("is_sent_by_autopilot") is True:
            ai_seen = True
            followed = [x for x in later if x.get("direction") == "inbound"
                        and (parse_time(x.get("created_at")) or now) - when <= window]
            if any(FOLLOW_UP.search(x.get("body") or "") for x in followed):
                found.add("guest_followed_up")
            if PROMISE.search(m.get("body") or ""):
                kept = any(x.get("direction") == "outbound"
                           and (parse_time(x.get("created_at")) or now) - when <= window for x in later)
                if not kept and now - when > window:
                    found.add("unkept_promise")
        elif outbound and sender == "user" and not copilot and (m.get("sender") or {}).get("user_id") not in automated:
            found.add("teammate_after_ai" if ai_seen else "teammate_reply")
    if msgs and msgs[-1].get("direction") == "inbound" and NEEDS_REPLY.search(msgs[-1].get("body") or ""):
        last = parse_time(msgs[-1].get("created_at")) or now
        if now - last > timedelta(hours=2):
            found.add("unanswered")
    return found


def score_signals(conversation):
    def low(key):
        v = conversation.get(key)
        return isinstance(v, (int, float)) and not isinstance(v, bool) and 1 <= v <= LOW_SCORE
    found = {"low_score"} if any(low(k) for k in SERVICE_SCORES) else set()
    return found | ({"low_stay_score"} if low("stay_quality_score") else set())


def run_signals(run):
    """Signals from one run: failures, sends the guest never got, and copilot drafts people rejected or changed."""
    found = set()
    if run.get("status") == "failed":
        found.add("run_failed")
    elif run.get("disposition") in FAILED:
        found.add("run_" + run["disposition"])
    if run.get("autopilot_sent") is False and run.get("disposition") in ("resolved", "escalation_and_answer"):
        found.add("run_not_sent")
    if run.get("proposal_outcome") in ("edited", "dismissed"):
        found.add("proposal_" + run["proposal_outcome"])
    return found


def called_after(messages, calls, repeat_hours, now):
    inbound = [parse_time(m.get("created_at")) for m in messages if m.get("direction") == "inbound"]
    inbound = [t for t in inbound if t]
    for c in calls:
        start = parse_time(c.get("started_at") or c.get("created_at"))
        if c.get("direction") == "inbound" and start and any(
                timedelta(0) <= start - t <= timedelta(hours=repeat_hours) for t in inbound):
            return True
    return False


SENDER_TYPES = {"contact", "user", "agent", "workflow", "external", "unknown"}


def known_sender(value):
    return value if value in SENDER_TYPES else "unknown"


def iso(when):
    return when.isoformat().replace("+00:00", "Z")


def collect(client, args, out, manifest):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=args.days)
    workspaces = client.request("GET", "/v1/workspaces").get("data") or []
    workspace = args.workspace
    if not workspace:
        if len(workspaces) != 1:
            names = [{"id": w.get("id"), "name": w.get("name")} for w in workspaces]
            raise SystemExit(json.dumps({"error": "pass --workspace", "workspaces": names}))
        workspace = workspaces[0]["id"]
    q = {"workspace_id": workspace}

    agents = client.paged("/v1/agents", q)
    wanted = set(args.agent or [])
    if wanted:
        agents = [a for a in agents if a["id"] in wanted or a.get("name") in wanted]
        if not agents:
            raise SystemExit("No agent matched --agent.")
    elif not args.all_agents:
        # Guest-answering agents have a message trigger, enabled or not; notifiers and schedulers don't.
        agents = [a for a in agents if any(t.get("type") == "message" for t in a.get("triggers") or [])]
    skip = set(args.skip_agent or [])
    agents = [a for a in agents if a["id"] not in skip and a.get("name") not in skip]
    names = {a["id"]: a.get("name") or a["id"] for a in agents}

    cases, run_counts, no_contact, capped = {}, Counter(), 0, []

    def case(contact_id):
        return cases.setdefault(contact_id, {"contact_id": contact_id, "runs": [], "escalations": [],
                                             "signals": set(), "latest": None})

    for a in agents:
        runs, cut = in_window(client, f"/v1/agents/{a['id']}/runs", {**q, "limit": 100}, since, args.max_pages)
        if cut:
            capped.append(f"runs of {names[a['id']]}")
        for r in runs:
            run_counts["failed" if r.get("status") == "failed" else str(r.get("disposition") or r.get("status") or "unknown")] += 1
            if not r.get("contact_id"):
                no_contact += 1
                continue
            c = case(r["contact_id"])
            c["runs"].append({"run_id": r.get("id") or r.get("run_id"), "agent": names[a["id"]],
                              "disposition": r.get("disposition"), "status": r.get("status"),
                              "created_at": r.get("created_at"), "autopilot_sent": r.get("autopilot_sent"),
                              "proposal_outcome": r.get("proposal_outcome")})
            c["signals"] |= run_signals(r)
            c["copilot"] = c.get("copilot") or r.get("proposal_outcome") is not None
            c["latest"] = max(filter(None, [c["latest"], r.get("created_at")]), default=None)

    escalations = []
    for status in ESCALATION_STATUSES:
        found, cut = in_window(client, "/v1/escalations", {**q, "status": status, "limit": 100}, since, args.max_pages)
        if cut:
            capped.append(f"{status} escalations")
        for e in found:
            if wanted and e.get("agent_id") not in names:
                continue
            escalations.append(e)
            if e.get("contact_id"):
                c = case(e["contact_id"])
                c["escalations"].append({"id": e.get("id"), "status": e.get("status"),
                                         "disposition": e.get("disposition"), "created_at": e.get("created_at"),
                                         "has_question": bool(e.get("questions_for_operator"))})
                c["signals"].add("escalation_" + str(e.get("status")))
                c["latest"] = max(filter(None, [c["latest"], e.get("created_at")]), default=None)

    # Escalations and failed runs before conversations whose only signals are silent or open-for-the-team runs.
    # Within each tier, take the newest case of each day in turn, so one busy day can't use up the budget.
    def spread(tier):
        by_day = {}
        for c in sorted(tier, key=lambda c: c["latest"] or "", reverse=True):
            by_day.setdefault((c["latest"] or "")[:10], []).append(c)
        days, out = [by_day[d] for d in sorted(by_day, reverse=True)], []
        while any(days):
            out += [d.pop(0) for d in days if d]
        return out
    flagged = [c for c in cases.values() if c["signals"]]
    failing = spread([c for c in flagged if c["signals"] & set(SEVERE)]) + \
        spread([c for c in flagged if not c["signals"] & set(SEVERE)])
    # Sample resolved conversations old enough for a follow-up, a call or an unkept promise to have shown.
    settled = iso(now - timedelta(hours=args.repeat_hours))
    resolved = sorted((c for c in cases.values() if not c["signals"] and (c["latest"] or "") < settled),
                      key=lambda c: c["latest"] or "", reverse=True)
    planned = (failing + resolved[:args.sample])[:args.max_conversations]
    sampled = sum(1 for c in planned if not c["signals"])
    skipped = {"failing_not_read": max(0, len(failing) - args.max_conversations),
               "resolved_not_sampled": len(resolved) - sampled}

    errors, sender_types, user_texts = Counter(), Counter(), Counter()
    for c in planned:
        try:
            looked = client.request("GET", "/v1/conversations/lookup",
                                    {**q, "contact_id": c["contact_id"], "include_messages": "false"})
            conv = (looked.get("data") or {}).get("conversation") or {}
            reservation = conv.get("reservation") or {}
            c.update(conversation_id=conv.get("id"), channel=conv.get("channel"), ai_paused=conv.get("ai_paused"),
                     listing_id=reservation.get("listing_id"), reservation_status=reservation.get("status"),
                     check_in=reservation.get("check_in"), check_out=reservation.get("check_out"),
                     scores={k: conv.get(k) for k in SCORES + ("sentiment",)})
            c["signals"] |= score_signals(conv)
            messages, truncated = [], False
            if conv.get("id"):
                query = {**q, "limit": 100, "order": "asc", "created_after": iso(since)}
                for data, more in pages(client, f"/v1/conversations/{conv['id']}/messages", query, args.max_pages):
                    messages += data
                    truncated = more
            c["messages_read"], c["truncated"] = len(messages), truncated
            for m in messages:
                if m.get("direction") == "outbound":
                    kind = known_sender((m.get("sender") or {}).get("type"))
                    sender_types[kind] += 1
                    if kind == "user" and m.get("body"):
                        user_texts[" ".join(m["body"].split()).lower()] += 1
            c["signals"] |= signals(messages, now, args.repeat_hours, copilot=c.get("copilot", False),
                                    automated=frozenset(args.automated_user or []))
            if args.calls:
                calls = client.request("GET", f"/v1/contacts/{c['contact_id']}/calls",
                                       {**q, "limit": 50, "order": "desc"}).get("data")
                if isinstance(calls, list) and called_after(messages, calls, args.repeat_hours, now):
                    c["signals"].add("called_after_message")
        except ApiError as err:
            if err.status in (401, 403):
                raise
            errors[f"HTTP {err.status}" if err.status else "network"] += 1
            c["read_error"] = str(err)
        except IncompleteExport as err:
            errors["incomplete messages"] += 1
            c["read_error"] = str(err)

    zone, zone_name = timezone.utc, "UTC"
    try:
        tz = (client.request("GET", f"/v1/workspaces/{workspace}/settings").get("data") or {}).get("timezone")
        if tz and ZoneInfo:
            zone, zone_name = ZoneInfo(tz), tz
    except (ApiError, KeyError, ValueError):
        pass
    start, end = since.astimezone(zone).date().isoformat(), now.astimezone(zone).date().isoformat()
    rates = {}
    for name in ("automation_rate", "resolution_rate"):
        try:
            rates[name] = client.request("GET", f"/v1/insights/{name}",
                                         {**q, "start_date": start, "end_date": end}).get("data")
        except ApiError as err:
            if err.status in (401, 403):
                raise
            rates[name] = {"error": str(err)}

    for c in failing[args.max_conversations:]:
        c["messages_read"], c["not_read"] = 0, True
    kept = planned + failing[args.max_conversations:]
    for c in kept:
        c["signals"] = sorted(c["signals"])
        c.pop("latest", None)
        c.pop("copilot", None)
    read = [c for c in kept if not c.get("not_read")]
    write(out, "cases.json", kept, manifest)
    write(out, "escalations.json", escalations, manifest)
    write(out, "rates.json", {"start_date": start, "end_date": end, "scope": "whole workspace",
                              "dates": f"calendar days in {zone_name}", **rates}, manifest)

    signal_counts = Counter(s for c in read for s in c["signals"])
    listings = Counter(c.get("listing_id") for c in read if c["signals"] and c.get("listing_id"))
    auto = rates.get("automation_rate") or {}
    return {
        "workspace_id": workspace, "window": {"start": start, "end": end, "days": args.days, "timezone": zone_name},
        "agents": len(agents), "runs": dict(run_counts), "runs_without_contact": no_contact,
        "escalations": dict(Counter(str(e.get("status")) for e in escalations)),
        "escalations_with_operator_question": sum(bool(e.get("questions_for_operator")) for e in escalations),
        "conversations_with_failure_signals": len(failing), "conversations_read": len(read),
        "not_read": skipped, "read_errors": dict(errors),
        "page_cap_reached": capped,
        "outbound_by_sender_type": dict(sender_types),
        # The same text sent as a "user" in several conversations is likely an automation, not a teammate.
        "repeated_user_texts": sum(1 for n in user_texts.values() if n >= 3),
        "signals": dict(signal_counts.most_common()),
        "listings_with_most_cases": [{"listing_id": k, "cases": v} for k, v in listings.most_common(10)],
        "workspace_automation_rate": {k: auto.get(k) for k in ("numerator", "denominator", "rate", "formula_version")
                            if isinstance(auto, dict)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="new, empty output folder (created with mode 700)")
    parser.add_argument("--workspace", help="workspace ID; optional when the token sees exactly one")
    parser.add_argument("--days", type=int, default=30, help="window in days, ending now (default 30, max 90)")
    parser.add_argument("--agent", action="append",
                        help="agent name or ID (repeatable); default every agent with a message trigger")
    parser.add_argument("--all-agents", action="store_true", help="include agents without a message trigger")
    parser.add_argument("--automated-user", action="append",
                        help="user ID whose messages are the operator's own automations, not a teammate (repeatable)")
    parser.add_argument("--skip-agent", action="append",
                        help="agent name or ID to leave out (repeatable), for protected or out-of-scope agents")
    parser.add_argument("--sample", type=int, default=100,
                        help="resolved conversations to check for outcome signals (default 100)")
    parser.add_argument("--max-conversations", type=int, default=300,
                        help="conversations to read in total, failing ones first (default 300)")
    parser.add_argument("--repeat-hours", type=int, default=24,
                        help="hours after an AI reply in which a guest follow-up counts against it, and after a guest "
                             "message in which a call does (default 24)")
    parser.add_argument("--calls", action="store_true", help="also read each contact's calls (one request per contact)")
    parser.add_argument("--max-pages", type=int, default=100, help="page cap per list (default 100 pages of 100)")
    parser.add_argument("--min-interval", type=float, default=1.0,
                        help="seconds between requests (default 1.0); the rate limit is shared with live guest traffic")
    args = parser.parse_args()
    if not 1 <= args.days <= 90 or args.sample < 0 or args.max_conversations < 1 or args.max_pages < 1:
        print("--days must be 1-90; --sample, --max-conversations and --max-pages must be positive.", file=sys.stderr)
        return 2

    token = os.environ.get("CONDUIT_API_TOKEN")
    if not token:
        print("Set CONDUIT_API_TOKEN to a Conduit API token. It is never printed.", file=sys.stderr)
        return 2
    if os.path.exists(args.out) and (not os.path.isdir(args.out) or os.listdir(args.out)):
        print(f"{args.out} exists and is not empty. Use a new folder.", file=sys.stderr)
        return 2
    os.makedirs(args.out, mode=0o700, exist_ok=True)
    os.chmod(args.out, 0o700)

    client = Client(token, args.min_interval)
    manifest = {}
    try:
        summary = collect(client, args, args.out, manifest)
    except SystemExit as stop:
        print(stop.code, file=sys.stderr)
        return 2
    except (ApiError, IncompleteExport) as err:
        fd = os.open(os.path.join(args.out, "INCOMPLETE"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(f"{err}\n{getattr(err, 'detail', '')}\n")
        print(f"{err}. Details are in {os.path.join(args.out, 'INCOMPLETE')}", file=sys.stderr)
        if isinstance(err, IncompleteExport):
            return 5
        return 3 if err.status in (401, 403) else 4

    taken = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write(args.out, "manifest.json", {"complete": True, "taken_at_utc": taken, **summary, "files": manifest}, {})
    print(json.dumps({"out": os.path.abspath(args.out), "complete": True, **summary, "requests": client.calls}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
