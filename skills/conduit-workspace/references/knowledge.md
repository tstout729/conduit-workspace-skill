# Knowledge

Read this to build, audit, enrich, restore or test property knowledge.

Contents: 1. Sources · 2. A complete listing · 3. Access and credentials · 4. Scope and structure · 5. Inventory and edit safely · 6. PMS-synced articles · 7. Learn each answer once · 8. Test retrieval

## 1. Sources

Use them in this order:

1. The field team's property notes and trackers (locks, spare keys, Wi-Fi, quirks).
2. A walkthrough of each home by its owner or manager.
3. PMS fields such as check-in instructions, Wi-Fi and house rules. When a fact disagrees with the PMS, fix the PMS when you're authorized to. Otherwise use a documented override (section 6), never a silent contradiction.
4. Answers people gave guests in escalated conversations.
5. Chat history. Expect little: it is mostly dispatch noise.

Save durable facts. Skip one-off defects already being fixed. Give a temporary notice its removal condition. Write a fleet-wide pattern once, such as how a lock model behaves, in a group- or workspace-scoped article.

Err toward more information. A knowledge base that is too thin causes lockouts and silent turns; one with extra true detail costs little.

## 2. A complete listing

Each item below once caused a wrong answer or a human takeover when missing.

**Property information**
- Rooms and beds with exact sizes; full versus half baths. For a reduced listing, which rooms are used and the guest limit.
- Wi-Fi network and password.
- Router location, and whether the guest can reach it to restart it.
- Breaker panel, water shutoff and water heater locations.
- Thermostat or heat-pump steps, including multi-zone rules.
- TV and streaming; appliance quirks (induction hob, hot-water switch). Anything out of service gets a removal condition.
- Laundry, trash and recycling (route and day), parking type and rules.
- Where common items live: kitchen basics, supplies, linens, cribs.
- Checkout steps.

**Access** (only for the verified current guest, during the access window)
- Entry route for every door: gate, building, lobby, unit. Lock type and how its code works.
- When codes activate, and any listing exception.
- The backup path, served by a tool.
- The physical spare: exact location and lockbox code.
- Storage or laundry codes the guest may use, for this home only.

Conduit's listing scope controls which listing's search sees an article. It does not check the guest, the stay or the time. Deliver entry codes through a tool or runtime that enforces those checks; keep them in an article only where that enforcement is verified.

**Keep out of knowledge:** live lock or device status, prices (the PMS owns them), agent behavior ("notify the team", "tell the guest X"), and internal language.

Score each listing Present, Vague or Absent per fact by reading the full articles. Count a fact only if the guest can reach and act on it.

## 3. Access and credentials

**Right guest, right unit, right time.**
- The verified current guest gets everything for their own unit: door flow, backup path, spare location and code, storage and laundry codes. Before the access window, non-entry details like Wi-Fi are fine.
- Over-stripping access details caused lockouts. A missing spare once cost a stay.
- Never serve another home's code. Isolate homes by the codes recorded for each one, not by address grouping. Compare against smart-lock codes, mechanical keypads, spare boxes, staff and master codes, and codes written in words. If the code inventory can't be read, fail closed.
- Keep master and staff codes out of articles. If the operator allows a last-resort code, issue one per home from a gated tool. Never issue a code that opens other homes or staff areas.
- When you find a code in prompt text, check what else it opens before moving it anywhere. A "laundry code" can turn out to be a master code.
- Publish only codes that work on the physical lock today. Listing variants that share a lock share its code.
- Keep credentials out of transcripts and outside graders. Write code-bearing articles with a script, mask previews, and use keyed hashes for comparisons.
- Keep a non-AI path for access details (portal or scheduled message), so entry never depends on the agent.

## 4. Scope and structure

- Set `entity_ids` on every content node: a listing ID, `group:<id>` or `unit:<listingId>:<subunitId>`. An empty list is workspace-wide and reaches every listing's search. Folders can't carry scope.
- Use the operator's existing article structure. One working pattern: property information plus access, next to the PMS article. Split a topic out when that improves retrieval.
- Keep one fact in one maintained place. Two versions of a fact is the most common cause of inconsistent answers.
- Give every bookable variant (reduced-bedroom, combined, sub-unit) complete scoped coverage. Reuse shared articles through scope where you can; write only the differences separately. A variant with only its PMS article answers badly.
- Prefer focused articles; they retrieve better than long mixed ones.
- Preserve each manual's existing voice. A generic template once had to be rolled back the same day.

## 5. Inventory and edit safely

1. **Enumerate.** Use `POST /v1/kb/nodes/search` with a cursor and `total_count`. `GET /v1/kb/nodes` lists at most 100 children and ignores cursors; one import built on it captured 660 of 1,367 articles.
2. **Snapshot.** Save full bodies privately before any bulk edit. Check the snapshot restores.
3. **Compare facts.** For each affected fact: current text, evidence, destination, and keep, change or remove. Remove a fact only when newer authoritative evidence contradicts it and the operator approves.
4. **Check preservation line by line.** Similarity scores fail. An 85% word-overlap check let a king bed revert to queen and a full bath to half.
5. **Pilot.** Run a few listings end to end, including the next PMS sync. Then batch small within the rate budget. Crawl and diff after each batch. Stop on unexpected removals, errors or any failed guest send.
6. **Watch for silent loss.** Fingerprint articles on a schedule. Alert on deletion, a large shrink or a lost access section.

Write traps:
- Send `entity_ids` alone in its own PATCH; combined with other fields it fails.
- `DELETE` removes the node and all its descendants.
- `tags` and `metadata` replace the whole set.
- An uncertain create can duplicate on retry. Search by title before retrying.

Never let an automated cleanup or "anti-hallucination" pass run without a snapshot and an approved removal list. Two such passes deleted or templated hundreds of access articles. Nobody noticed for ten weeks, until a guest was locked out.

## 6. PMS-synced articles

- The sync owns them; direct edits get overwritten. Fix the PMS field. If the operator permits an override instead, add a scoped manual article, say in it which fact it replaces, and test retrieval after the next sync.
- Sync runs on a schedule set in the UI. It refreshes only imported listings and skips listings inactive in Conduit. New listings need an import.
- An API refresh may not exist. Verify after the next scheduled sync, not right after your edit.
- Keep each listing's Conduit active state matched to the PMS. Imported listings arrive active, answered and billed.
- If the operator keeps a canonical knowledge base elsewhere, write there first and sync down. Conduit must not hold facts the canonical source lacks; treat Conduit-only lines as proposals.

## 7. Learn each answer once

When the agent lacks a fact about the home, the agent never guesses. Recommended default, once a person reliably answers what the agent leaves:

1. The agent answers the verified part and leaves the rest out. If nothing useful remains, it stays silent.
2. A person answers the guest.
3. The answer goes into that listing's article the same day, as one plain paragraph.

Never append credentials, names, phone numbers or temporary arrangements. Confirm the listing before writing.

Conduit's node PATCH has no conditional write. Re-fetch the node and compare `updated_at` first. Run one write at a time. Don't claim atomic protection. Use a real compare-and-swap if the canonical store offers one.

## 8. Test retrieval

- Test through the agent's own listing-scoped search. An admin token may not see restricted articles, so an admin miss proves nothing.
- Ask one fact per query.
- `POST /v1/kb/search` returns chunks (at most 50), not whole articles. Compact listing and amenity tools truncate. Absence in a search result is not absence in the home.
- Treat a weak match as final in instructions. Don't tell the agent to re-search.
- After edits, check scoped queries for stale contradictions and for facts leaking from other listings.
