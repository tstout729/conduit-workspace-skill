#!/usr/bin/env python3
"""Read-only snapshot of a Conduit workspace's agent configuration.

Writes JSON files into a new private folder for review, diffing and rollback
planning. It sends GET requests, plus the read-only knowledge search POST
when --kb is given. It never changes anything in Conduit.

Examples:
  CONDUIT_API_TOKEN=... python3 conduit_snapshot.py --out /tmp/conduit-snap
  python3 conduit_snapshot.py --out snap --workspace WS_ID --kb
  python3 conduit_snapshot.py --out snap --kb --kb-bodies   # bodies may hold codes

Output files: workspace.json, agents.json, skills.json, custom-tools.json,
agent-tools/<agent_id>.json, agent-connections/<agent_id>.json,
listings.json, listing-groups.json and conversation-tags.json (each skipped,
and named under "skipped" in the manifest, if its route is unavailable),
kb-nodes.json (with --kb), and manifest.json, written last, with
"complete": true and the SHA-256 of every file. A failed run leaves an
INCOMPLETE file instead; never use that folder as a rollback source.

Not covered: workflows, voice agents, knowledge sources, triggers beyond
those embedded in agents, workspace-level instructions, escalation rules and
hooks. Fetch any of those you plan to change separately.

Prints a JSON summary on stdout. Exit codes: 0 complete, 2 usage,
3 auth, 4 API or network error, 5 incomplete export.
"""
import argparse
import email.utils
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://api.conduit.ai"


class ApiError(Exception):
    """str() carries only the route and status; the response detail stays in the private folder."""

    def __init__(self, status, path, detail):
        super().__init__(f"{'HTTP ' + str(status) if status else 'request failed'} for {path.split('?')[0]}")
        self.status = status
        self.detail = detail[:2000]


class IncompleteExport(Exception):
    pass


def retry_delay(header):
    """Seconds to wait from a Retry-After header (seconds or HTTP date), bounded; 10 if unreadable."""
    try:
        return max(0.0, min(float(header), 120.0))
    except (TypeError, ValueError):
        pass
    try:
        when = email.utils.parsedate_to_datetime(header)
        return max(0.0, min((when - datetime.now(timezone.utc)).total_seconds(), 120.0))
    except (TypeError, ValueError, IndexError):
        return 10.0


class Client:
    def __init__(self, token, min_interval):
        self.token = token
        self.min_interval = min_interval
        self.last = 0.0
        self.calls = 0

    def request(self, method, path, query=None, body=None):
        url = BASE + path
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(4):
            wait = self.min_interval - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("Authorization", f"Bearer {self.token}")
            req.add_header("Accept", "application/json")
            if data is not None:
                req.add_header("Content-Type", "application/json")
            self.last = time.monotonic()
            self.calls += 1
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    payload = json.load(resp)
            except urllib.error.HTTPError as err:
                text = err.read().decode(errors="replace")
                if err.code == 429 and attempt < 3:
                    delay = retry_delay(err.headers.get("Retry-After"))
                    print(f"429 on {path}; waiting {delay:.0f}s", file=sys.stderr)
                    time.sleep(delay)
                    continue
                raise ApiError(err.code, path, text) from None
            except (urllib.error.URLError, TimeoutError, ValueError) as err:
                raise ApiError(0, path, f"{type(err).__name__}: {err}") from None
            if not isinstance(payload, dict):
                raise ApiError(0, path, "response was not a JSON object")
            return payload
        raise ApiError(429, path, "rate limited after retries")

    def paged(self, path, query):
        items, cursor, seen = [], None, set()
        while True:
            page = self.request("GET", path, {**query, "limit": 100, "cursor": cursor})
            data = page.get("data")
            if not isinstance(data, list) or not isinstance(page.get("has_more"), bool):
                raise IncompleteExport(f"{path}: response lacks a data list or a boolean has_more")
            items.extend(data)
            if not page["has_more"]:
                return items
            cursor = page.get("next_cursor")
            if not cursor or cursor in seen:
                raise IncompleteExport(f"{path}: has_more is true but the cursor is missing or repeated")
            seen.add(cursor)


LISTING_FIELDS = ("listingId", "name", "internalName", "publicName", "isActive", "active",
                  "status_source", "status_changed_at", "pmsPlatform", "timezone")
TAG_FIELDS = ("id", "name", "kind", "parent_tag_id", "urgency_level", "action_item", "shown_in_inbox", "count")


def camel_paged(client, path, query, key):
    """All items under data[key] from routes that page with data.nextCursor and data.hasMore (50 per page at most)."""
    items, cursor, seen = [], None, set()
    while True:
        page = client.request("GET", path, {**query, "limit": 50, "cursor": cursor}).get("data")
        if not isinstance(page, dict) or not isinstance(page.get(key), list) or not isinstance(page.get("hasMore"), bool):
            raise IncompleteExport(f"{path}: response lacks data.{key} or a boolean data.hasMore")
        items.extend(page[key])
        if not page["hasMore"]:
            return items
        cursor = page.get("nextCursor")
        if not cursor or cursor in seen:
            raise IncompleteExport(f"{path}: hasMore is true but the cursor is missing or repeated")
        seen.add(cursor)


def listing_exports(client, query):
    """Listings with their Conduit active state, and listing groups with their members."""
    listings = [{k: l.get(k) for k in LISTING_FIELDS} for l in camel_paged(client, "/v1/listings/catalog", query, "listings")]
    groups = []
    for g in camel_paged(client, "/v1/listing-groups", query, "groups"):
        members = camel_paged(client, f"/v1/listing-groups/{g.get('groupId')}/listings", query, "listings")
        groups.append({"groupId": g.get("groupId"), "name": g.get("name"),
                       "listings": [{k: m.get(k) for k in ("listingId", "listingRef", "isActive", "found")} for m in members]})
    return listings, groups


def optional(name, fetch, skipped):
    """Runs fetch(); a missing, changed or forbidden route, or a malformed page, is recorded in skipped instead of failing."""
    try:
        return fetch()
    except ApiError as err:
        if err.status in (400, 403, 404, 405, 422, 501):
            skipped[name] = f"HTTP {err.status}"
            return None
        raise
    except IncompleteExport as err:
        skipped[name] = str(err)
        return None


def kb_inventory(client, workspace, bodies):
    items, cursor, seen, total = [], None, set(), None
    while True:
        pagination = {"page_size": 100}
        if cursor:
            pagination["cursor"] = cursor
        page = client.request(
            "POST", "/v1/kb/nodes/search", {"workspace_id": workspace},
            {"pagination": pagination, "include_body": bodies},
        )
        data = page.get("data")
        if not isinstance(data, list) or not isinstance(page.get("has_more"), bool):
            raise IncompleteExport("knowledge search: response lacks a data list or a boolean has_more")
        count = page.get("total_count", total)
        if count is not None and (not isinstance(count, int) or isinstance(count, bool) or count < 0):
            raise IncompleteExport("knowledge search: total_count is not a non-negative integer")
        total = count
        for node in data:
            if not bodies:
                node.pop("body", None)
            items.append(node)
        if not page["has_more"]:
            break
        cursor = page.get("next_cursor")
        if not cursor or cursor in seen:
            raise IncompleteExport("knowledge search: has_more is true but the cursor is missing or repeated")
        seen.add(cursor)
    if total is not None and total != len(items):
        raise IncompleteExport(f"knowledge search: got {len(items)} nodes but total_count is {total}")
    return items, total


def write(out, rel, payload, manifest):
    path = os.path.join(out, rel)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    raw = json.dumps(payload, indent=1, sort_keys=True).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(raw)
    manifest[rel] = hashlib.sha256(raw).hexdigest()


def export(client, args, manifest):
    workspaces = client.request("GET", "/v1/workspaces").get("data") or []
    workspace = args.workspace
    if not workspace:
        if len(workspaces) != 1:
            names = [{"id": w.get("id"), "name": w.get("name")} for w in workspaces]
            raise SystemExit(json.dumps({"error": "pass --workspace", "workspaces": names}))
        workspace = workspaces[0]["id"]
    write(args.out, "workspace.json", [w for w in workspaces if w.get("id") == workspace], manifest)

    query = {"workspace_id": workspace}
    counts = {"workspace_id": workspace}
    agents = client.paged("/v1/agents", query)
    write(args.out, "agents.json", agents, manifest)
    skills = client.paged("/v1/skills", query)
    write(args.out, "skills.json", skills, manifest)
    tools = client.paged("/v1/custom-tools", query)
    write(args.out, "custom-tools.json", tools, manifest)
    counts.update(agents=len(agents), skills=len(skills), custom_tools=len(tools))
    for agent in agents:
        aid = agent["id"]
        access = client.request("GET", f"/v1/agents/{aid}/tools", query).get("data")
        conns = client.request("GET", f"/v1/agents/{aid}/connections", query).get("data")
        if not isinstance(access, list) or not isinstance(conns, list):
            raise IncompleteExport(f"agent {aid}: tools or connections response has no data list")
        write(args.out, f"agent-tools/{aid}.json", access, manifest)
        write(args.out, f"agent-connections/{aid}.json", conns, manifest)
    skipped = {}
    found = optional("listings", lambda: listing_exports(client, query), skipped)
    if found:
        write(args.out, "listings.json", found[0], manifest)
        write(args.out, "listing-groups.json", found[1], manifest)
        counts.update(listings=len(found[0]), listing_groups=len(found[1]))
    tags = optional("conversation-tags", lambda: client.paged("/v1/conversation-tags", query), skipped)
    if tags is not None:
        write(args.out, "conversation-tags.json", [{k: t.get(k) for k in TAG_FIELDS} for t in tags], manifest)
        counts.update(conversation_tags=len(tags))
    if skipped:
        counts["skipped"] = skipped
    if args.kb or args.kb_bodies:
        nodes, total = kb_inventory(client, workspace, args.kb_bodies)
        write(args.out, "kb-nodes.json", nodes, manifest)
        counts.update(kb_nodes=len(nodes), kb_total_count=total)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="new, empty output folder (created with mode 700)")
    parser.add_argument("--workspace", help="workspace ID; optional when the token sees exactly one")
    parser.add_argument("--kb", action="store_true", help="include the knowledge node inventory (metadata)")
    parser.add_argument("--kb-bodies", action="store_true", help="include knowledge bodies; they may contain access codes")
    parser.add_argument("--min-interval", type=float, default=1.0,
                        help="seconds between requests (default 1.0); the rate limit is shared with live guest traffic")
    args = parser.parse_args()

    token = os.environ.get("CONDUIT_API_TOKEN")
    if not token:
        print("Set CONDUIT_API_TOKEN to a Conduit API token. It is never printed.", file=sys.stderr)
        return 2
    if os.path.exists(args.out) and (not os.path.isdir(args.out) or os.listdir(args.out)):
        print(f"{args.out} exists and is not empty. Use a new folder so earlier snapshots stay intact.", file=sys.stderr)
        return 2
    os.makedirs(args.out, mode=0o700, exist_ok=True)
    os.chmod(args.out, 0o700)

    client = Client(token, args.min_interval)
    manifest = {}
    try:
        counts = export(client, args, manifest)
    except SystemExit as stop:
        print(stop.code, file=sys.stderr)
        return 2
    except (ApiError, IncompleteExport) as err:
        fd = os.open(os.path.join(args.out, "INCOMPLETE"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(f"{err}\n{getattr(err, 'detail', '')}\nDo not use this folder as a rollback snapshot.\n")
        print(f"{err}. Details are in {os.path.join(args.out, 'INCOMPLETE')}", file=sys.stderr)
        if isinstance(err, IncompleteExport):
            return 5
        return 3 if err.status in (401, 403) else 4

    taken = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write(args.out, "manifest.json", {"complete": True, "taken_at_utc": taken, **counts, "files": manifest}, {})
    print(json.dumps({"out": os.path.abspath(args.out), "complete": True, **counts, "requests": client.calls}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
