# Conduit skills and tools

Read this to create, route, fix or retire Conduit skills, custom tools, workflows or utility agents.

Contents: 1. Choose the object · 2. Descriptions · 3. Skill body · 4. Sharing and assignment · 5. Tool contract · 6. The backend decides · 7. Release and retire · 8. Workflows and utility agents

## 1. Choose the object

| Need | Object |
| --- | --- |
| A fact | Knowledge |
| A process that needs judgment | Conduit skill |
| Live data or an action | Custom tool, paired with the Conduit skill that uses it |
| The same action every time | Workflow, or your own scheduler |
| Dispatch, digests, staff follow-up | Your operations system, not the guest agent |

Update the existing owner before adding a Conduit skill. Never build a tool that returns facts knowledge already holds; a property-facts tool once competed with the knowledge base and was retired.

## 2. Descriptions

The description decides which Conduit skill loads.

- Shape: "Own [intents, in the guest's words, including follow-ups]. [Neighbor intent] belongs to [owner skill]. Uses [tool]. Never [claim it must not make]."
- Give each intent exactly one owner. Name excluded neighbors in both descriptions.
- Keep it to 150–500 characters, specific enough to win and narrow enough not to compete.
- Review the description, body, tool description, tool parameters and tool result text together. A broad maintenance description once won heat-pump questions and skipped the climate skill's one key question.

## 3. Skill body

```markdown
# <Scenario> handler
Use when <concrete triggers, including follow-ups to the same issue>.

## Not this skill
- <Neighbor intent>: <owner skill>.
- <Strict-silence cases>: no reply.

## Required context
1. Use injected context; look up only what is missing.
2. Confirm <reservation, listing, status, dates, booking source>. Never ask the guest which channel.
3. Call @<tool> with exact IDs and the guest's full latest message.
4. For static facts, search knowledge once, scoped to this listing. A weak result is final; omission means unknown.

## Decide from the result
- `<value_a>`: <what to convey>; <permitted action>.
- Failure or unknown: only an independently verified step or a needed question; otherwise silence.

## Action (writes only)
- Call @<write-tool> only after <explicit acceptance or consent>.
- Confirm only when `<flag>` is true. Otherwise don't claim it, don't retry, keep it open.
- This tool does not <non-effects>.

## Reply
- Cover <points>, in fresh host wording. Keep values exact.
- No internal words. No ETA or completion claim without a confirming result. Say it once.

## Resolution
1. Give one step at a time; wait for the guest's result.
2. Resolved: reply and mark done.
3. Still open: one permitted handoff, then silence (`no_op`, open).
```

Rules for bodies:
- A "Required context" list does not make the agent call those tools. Check the trace, and enforce critical preconditions in the backend.
- Ask the one question that changes the next step, such as "heating or cooling?".
- Accept natural language: "around 1", "we just left".
- Resolve each `@` mention by its type (tool, Conduit skill, workflow, listing, status). Confirm the target agent can actually use it. The bundled lint gives hints, not proof.
- Keep shared blocks (time wording, the silence format) in one owner and refer to it by name. Copied paragraphs drift apart.

## 4. Sharing and assignment

- Skills created in the UI, by the Operator or from the Marketplace attach to every current agent. Create by API with `auto_assign_to_existing_v2_agents: false`.
- Attach with MCP `set_agent_skill_access`, or a full `skill_ids` PATCH, which replaces the list.
- Deleting a Conduit skill removes it from every agent.
- If a skill serves a protected agent, copy it, attach the copy to the target and leave the original alone.
- Brand copies drift. Diff the forks and fix wrong-brand labels.

## 5. Tool contract

```text
name: <verb>-<object>     get-/check- read; record-/approve-/request- write
enable_globally: false    enable per agent
description (<=1024; aim for <=400): <Reads|Records> <what> for the exact <entity>.
  Use for <scenario>. Confirm <claim> only when rawData.<flag> is true.
  It does not <notify / dispatch / change dates>.
parameters:
  contact_id, reservation_id   required; "from runtime context, never guessed"
  guest_statement              writes: the guest's entire latest message, not a paraphrase
  source_message_id            optional; the server resolves it when absent
  <choice>                     enum; every value a Conduit skill names must be listed here
returns {message, rawData}:
  ok:       "<What is now true>. <What this does not establish>. <Next allowed step>."
  rejected: "<Claim> is not confirmed. Do not say <claim>." rawData.success=false, reason
  unknown:  "Outcome unknown. Do not claim success or repeat the write." rawData.<flag>=null
  retired:  "Retired; use <replacement>." rawData.retired=true, replacement_tool
```

- Code runs as Python `main(**params)` or JavaScript `async function main(params)`. It must return a string `message`; `rawData` is optional. Check `GET /v1/custom-tools/runtimes` for packages.
- Changing code bumps `version`. Validate input and return a structured failure; don't throw. Set a request timeout.
- Write `message` as directions to the agent, not guest text.
- Use separate fields for separate facts: requested, recorded, applied and fulfilled are different states. Unknown is `null`, not `false`.
- Set no invented defaults, such as a party size or a standard time.
- Confirm how the workspace supplies secrets to tool code before writing it. Never hard-code one.
- `POST /v1/custom-tools/{id}/run` executes for real. A 200 response with `success: false` is a failure.
- If a Conduit skill tells the agent to pass a value the enum lacks, the model substitutes another. Keep them in lockstep and validate at the receiver.

## 6. The backend decides

- Put eligibility in a tested endpoint. One call rechecks, records idempotently and returns the confirmed result; the agent only phrases it.
- Bind consent and provenance to the real inbound message on the server. Never accept a consent flag the model supplies.
- Take the booking source from the reservation, never the message channel. A text message is not a direct booking.
- Scope every read to the guest's own stay, contact and listing.
- Record the attempt durably before sending a physical command (unlock, code change). Never retry an attempt whose result is unknown.
- Choose one escalation owner. Prevent duplicate notifications across agents, tools and observers.
- Never expose a path that changes data as a read-only lookup.

## 7. Release and retire

1. Deploy the backend.
2. Enable the tool for the target agent only.
3. Update the Conduit skill.

Before the backend ships, write skills that behave correctly with both the old and new results. To retire a tool, make its code return `retired: true` and the replacement name; disable toggles have failed to persist. Inventory every consumer before closing an old route.

## 8. Workflows and utility agents

**Workflows**
- Creates and updates are drafts unless activated, and every update is a new version. Check the active version, not `enabled`.
- Run drift checks and activation as separate steps.
- Read the workflow schema before writing. Switch-off and trigger semantics differ by version.
- Proactive "ready" or offer messages need a real event, not a calendar gap.
- Track every automated send in an outbox: pending, dispatched, delivered, suppressed or failed. Claim each event once before dispatch.
- Count a send as delivered only from a receipt matched to the recipient, stay and listing. A "sent" stamp written before dispatch once hid a notice that never went out. Never retry an ambiguous send.
- Audit prompts and branch conditions for copy-paste errors and output names the agent never emits.

**Utility agents** (notifiers, auto-accept)
- Least-privilege tools, at most one message, fail closed, verify by re-reading.
- Dry-run with payloads that hit the skip paths.
- Webhook-triggered agents have their own config needs, such as an empty trigger `config` and `responseflow`. Check the current schema.
