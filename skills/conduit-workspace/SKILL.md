---
name: conduit-workspace
description: Build, audit, or improve a Conduit AI guest-messaging workspace (knowledge base, agent persona, guardrails, Conduit agent skills, custom tools, tests) so the AI resolves more conversations without a person. Use when setting up Conduit agents, raising the automation rate, or finding why an agent answered wrongly, stayed silent, or escalated. Not for writing a single guest reply.
---

# Conduit workspace

Turn a Conduit workspace into one that resolves most guest conversations alone, and safely. One short-term-rental operator reported moving from about 50% to over 90% automation with this method; the metric and the causes weren't independently measured. Their gains came from a loop, not one setup pass: measure, read what people still handled, fix the layer that caused it, test, repeat.

## Terms

- **Agent Skill**: this package, loaded by Claude Code or Codex.
- **Conduit skill**: a skill object inside Conduit (`/v1/skills`), attached to an agent through `skill_ids`.
- **Knowledge**: knowledge base nodes (articles). **Persona**: the agent's `instructions`. **Guardrail**: one entry in the agent's `guardrails`. **Tool**: a built-in, custom or integration tool the agent may call.
- **Automation**: a guest issue resolved with no human message or action. Fix the definition before you measure.

## Rules for the whole task

1. Read the operator's own rules for Conduit, guest content and protected agents first. They override this skill. Read their recent decision records too (change log, wiki, tickets): a configuration that looks broken may be off on purpose.
2. Settle the operator's choices before writing behavior: voice, unknown-fact handling, AI disclosure, who gets which access details, and who owns escalations. This skill's defaults are one operator's proven choices, not universal rules.
3. Confirm which runtime actually sends replies and which knowledge it reads. Editing an inactive agent may change nothing.
4. Use the Conduit REST API or MCP server. Discover the live schema first; fields, limits and routes change.
5. Treat an audit as read-only. Make live changes only with the operator's authorization for that change. Simulations and test agents count as writes.
6. Snapshot every object you will change, and every other agent that uses it, before writing. Read back with an independent GET afterward. A PATCH echo proves nothing.
7. Never bulk-delete, template or strip knowledge. Missing evidence is a gap to fill, not proof a fact is wrong.
8. Keep credentials out of persona, guardrails, skill bodies and tool code. Serve entry codes through a tool that checks the guest, the stay and the access window. Listing scope alone doesn't enforce timing.
9. Treat shared and global objects as edits to every agent. Copy a shared object for the target agent instead of editing the original.
10. Let the agent claim an action only when a tool result confirms it.
11. Test that the agent replies when it should, not only that it stays quiet. Over-silence and over-security are failures too.

## Put each fix in the layer that owns it

| Symptom in a real conversation | Owning layer | Read |
| --- | --- | --- |
| The trace shows no relevant source, or a fact was wrong | Knowledge | [Knowledge](references/knowledge.md) |
| Right facts, but stiff, canned or off-brand wording | Persona | [Persona and guardrails](references/persona-and-guardrails.md) |
| A leak, a false claim, an unsafe answer, or wrong silence | Guardrail, or a mode, tag or backend control | [Persona and guardrails](references/persona-and-guardrails.md) |
| Wrong process, wrong Conduit skill loaded, a step skipped | Conduit skill | [Skills and tools](references/skills-and-tools.md) |
| Needed live data or an action the agent couldn't take | Tool and its backend | [Skills and tools](references/skills-and-tools.md) |
| The agent never ran, or ran in the wrong mode or inbox | Runtime: mode, triggers, routing, listing state | [Automation loop](references/automation-loop.md) |

Conduit's own test applies: if the agent found nothing relevant, fix knowledge. If it found the right material and still answered badly, fix behavior.

## Choose the mode

**Raise automation** (default when the request is open-ended). Read [Automation loop](references/automation-loop.md) first.

1. Measure a baseline with Conduit's rate endpoints and your own unanswered-message counts.
2. Pull every conversation a person handled, the agent escalated, or the agent left silent in the window.
3. Read each thread and its run trace. Classify the cause and its owning layer.
4. Fix the largest class first, in its owning layer, for every listing it affects.
5. Replay those cases plus neighboring scenarios.
6. Apply and read back. Sample the next real runs, then remeasure.

**Build a new workspace or agent.**

1. Decide scope: brands, listings, channels, what stays human, and who picks up the agent's silence.
2. Build knowledge first.
3. Add tools for the most frequent live lookups.
4. Write the persona and guardrails.
5. Add Conduit skills for the most frequent human-handled cases.
6. Start in copilot or shadow mode. Expand autopilot in narrow steps ([Automation loop](references/automation-loop.md), trust ladder).

**Fix one reported bad answer.** Get the run trace. Decide whether the agent never ran or chose this outcome. Search every layer for the behavior, including tool descriptions and result text. Fix the owner and make the others agree. Copy before-text exactly from the snapshot. Replay the case with its neighbors.

**Audit.** Run the bundled scripts below. Then read in full every persona, guardrail, attached skill body and tool description in scope. Record what you couldn't read (workspace-level instructions, Behavior rules, hooks, workflows) as unchecked. Label each finding by evidence strength and owning layer. Change nothing.

## References

Read only what the task needs.

- [Automation loop](references/automation-loop.md): measuring automation, the improvement loop, the trust ladder, runs that never happened.
- [Knowledge](references/knowledge.md): building, auditing, editing or testing property knowledge and access details.
- [Persona and guardrails](references/persona-and-guardrails.md): voice, guardrails, silence rules, truthful claims.
- [Skills and tools](references/skills-and-tools.md): Conduit skills, custom tools, backend contracts, workflows.
- [API and testing](references/api-and-testing.md): read before live reads beyond the snapshot, any write, or any behavior test.

## Bundled scripts

Run them from this skill's folder; read them only if they fail. Both print JSON and never print the token.

- `python3 scripts/conduit_snapshot.py --out NEW_DIR [--workspace ID] [--kb] [--kb-bodies]`: read-only export of agents, Conduit skills, custom tools, each agent's tool access and connections, and optionally the full knowledge inventory. Needs `CONDUIT_API_TOKEN`. It refuses a non-empty folder and writes `manifest.json` with `"complete": true` only when every page arrived. It doesn't export workflows or workspace instructions. Keep the folder private; it can hold guest credentials.
- `python3 scripts/conduit_lint.py DIR [--agent NAME]`: offline hints from a snapshot: shared and global objects, personal or broken connections, unresolved `@` references, credential-like text (location only), oversized guardrails, restated paragraphs, orphan or disabled skills, unscoped knowledge. Read each hit in full before acting.

## Gotchas

- `PATCH /v1/agents/{id}` replaces `skill_ids` and `triggers` whole. Resend `guardrails` with their IDs. Prefer per-item MCP tools where they exist.
- Skills created in the Conduit UI attach to every agent. Create by API with `auto_assign_to_existing_v2_agents: false`.
- A custom tool with `enable_globally: true` reaches every agent, including protected ones.
- A per-agent tool disable can return success and not persist. Read it back. Retire a tool by making its code return a "retired" result.
- `enabled: true` does not mean running. Check `operation_mode`, triggers, inbox routing, listing active state and the active workflow version.
- Untagged knowledge nodes (empty `entity_ids`) surface for every listing. Workspace-level instructions reach every agent.
- API sends appear under the account owner's name. Never key a rule on who sent a message.
- `GET /v1/kb/nodes` stops at 100 children with no cursor. Inventory with `POST /v1/kb/nodes/search`.
- The API simulator can't attach a reservation. An unlinked test returns `no_op`, which looks like a pass.
- A guardrail can't reliably stop an agent. Use mode, routing, triggers or an urgent conversation tag.
- Conduit's automation rate counts answer-and-escalate as an AI send. Use `fully_autonomous` from the resolution rate for "handled alone".
- REST and MCP share one rate limit with live guest traffic, and take different argument names. Check each schema.

## Report

Answer the task that was asked. Put unrelated findings in one short "also noticed" list. End with this, in plain language:

1. Goal, scope, and protected or excluded agents and listings.
2. Metrics before and after: definition, window, numbers.
3. Each change: object, owning layer, cause, evidence, and state (drafted, applied, tested, live).
4. Tests run or planned: cases, results, and what they can't cover (for example, the API simulator can't attach a reservation).
5. Snapshot location and how to roll back.
6. Open items and decisions the operator must make.
