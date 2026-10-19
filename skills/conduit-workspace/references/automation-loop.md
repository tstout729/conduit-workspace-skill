# Automation loop

Read this to measure automation, collect and classify failures, run the improvement loop, keep fixes fixed, earn autopilot, or diagnose a run that never happened.

Contents: 1. Measure · 2. The loop · 3. Cause → layer · 4. The fix log · 5. Conduit's own views · 6. Practices from one operator's improvement · 7. Trust ladder · 8. Never ran versus chose silence

## 1. Measure

Write down the definition and window before you pull numbers.

| Measure | Source | Notes |
| --- | --- | --- |
| AI-sent share | `GET /v1/insights/automation_rate?workspace_id&start_date&end_date[&category_name]` | Sent decisions ÷ countable decisions. Answer-and-escalate counts as sent. Window ≤ 90 days. `breakdown.by_disposition` and the daily `series` show where the rest went. |
| Handled alone | `GET /v1/insights/resolution_rate`, field `fully_autonomous` | Resolved, sent, no teammate message, no escalation. Report it with its denominator: eligible autopilot threads only, excluding `no_op`, copilot, inactive and unlinked runs. Its `breakdown` splits threads by final disposition, human intervention and escalation. |
| Unanswered | Your own query over conversations | Latest guest message with no reply after 15 minutes and after 2 hours. |
| Came back | Conversations after an AI reply | The guest wrote again within 24 hours, a teammate stepped in, or the guest called. A rising share means replies that look automated aren't working. |
| Human outbound share | Outbound messages with `sender.type: user` | `is_sent_by_autopilot: false` also covers workflow, other agents and API sends (`workflow`, `agent`, `external`); separate them. |
| Human work off-thread | Your operations records | Staff actions the conversation never shows (calls, visits, refunds). |
| Quality | A read sample of sent replies, plus Conduit's scores | Unsupported claims, wrong listing, internal language, double replies, guest had to repeat. `GET /v1/conversations/lookup` returns `sentiment` and scores for customer sentiment, service quality and stay quality (1–5 when observed; the spec gives no range). |

- Insights endpoints allow about 10 requests per minute. Record `formula_version` and compare it before comparing periods.
- `no_op` counts, `autopilot_sent` (null means "not counted", not false) and test pass counts are not automation measures.
- A correct silent turn lowers the AI-sent share. Never chase the number with holding replies or by removing legitimate silence.
- If the operator moved some homes or channels to another system during the window, say so next to the number. A shrinking set of conversations changes a rate without any fix.

## 2. The loop

Run it daily during a push and weekly after.

1. **Collect.** Gather every conversation in the window that didn't end the way the operator intended. `scripts/conduit_failures.py` pulls the API signals into a private folder: one case per conversation with no message text, and an escalations file that holds guest messages and reviewer names. Keep the folder private.
   - **Escalations of every status** (`GET /v1/escalations`, each `status` in turn). `questions_for_operator` and `request_for_additional_info` say what the agent lacked. Resolved ones also hold the teammate's answer in the thread.
   - **Runs** that escalated, stayed silent (`no_op`), ended `unresolved` or failed (`GET /v1/agents/{id}/runs`; it filters by `status` only, so filter dispositions yourself). Some `no_op` turns are correct silence. A run with `autopilot_sent: false` decided to answer but nothing reached the guest. In copilot, a draft people edited or dismissed (`proposal_outcome`) is a failure too.
   - **Teammate replies**: a message with `sender.type: user` after the agent's reply, or a thread only teammates answered. In copilot, people send the approved drafts, so use `proposal_outcome` there instead.
   - **Outcome failures after an AI reply**, which no disposition shows:
     - the guest wrote again within 24 hours with a follow-up ("still", "again", "any update", "didn't work", "can't find");
     - the guest's last message got no reply;
     - the AI promised something ("I'll check", "let you know") and nothing followed;
     - the guest called after messaging (`GET /v1/contacts/{id}/calls`);
     - Conduit scored the service or the guest's sentiment low (2 or less). A low stay score usually points to a person or process cause;
     - the guest raised it in a review.
   - **What the operator flagged**, and the top issues from Conduit's Escalations tab (section 5).

   When there are more than about 150 cases, read every case in the three largest groups and a sample of the rest. The rate limit is shared with live guests.
2. **Read.** Read each full thread and its run (`GET /v1/agents/{id}/runs/{run_id}`): skills loaded, tool calls and results, sources, guardrails, `disposition_reason`. Read scheduled, workflow and portal messages the guest received before writing.
3. **Classify.** Name the cause with the table in section 3. A case can have two causes; record both. Tally by cause. Fix the largest agent class first.
4. **Fill the facts.** For a missing or wrong fact, take it in this order:
   1. Conduit's own question for the operator on the escalation names the gap.
   2. A teammate's answer in the thread is a candidate fact. Confirm with the operator that it is true for every stay before saving it.
   3. The operator's own sources ([Knowledge](knowledge.md), section 1).
   4. Ask the operator, in one short list, for what no source answers. Keep the list in the open-questions file ([Knowledge](knowledge.md), section 1).
5. **Fix the class.** Change the owning layer for every listing and scenario the cause affects, not the one thread. Then make every other layer agree with it. Give person and process causes to the operator as a list, with conversation IDs; don't patch the agent for them.
6. **Test.** Replay the cases, their neighboring scenarios and the reply-value cases ([API and testing](api-and-testing.md)).
7. **Ship.** Apply, read back, and prove the change from a real run whose trace shows the new skill, source or guardrail. Remeasure.
8. **Record.** Add each fix to the fix log (section 4). Save the rule once, where the operator keeps rules.
9. **Check recurrence.** On the next run, count new cases in each logged class since its fix.

The highest-yield habit: during the push, one person who knows the homes handles every escalated conversation. Each repeat becomes a knowledge fact, a Conduit skill change or a tool the same day.

## 3. Cause → layer

| Cause | What the conversation or trace shows | Fix |
| --- | --- | --- |
| Missing or wrong fact | No relevant source, a weak match, or a wrong value | Add or correct the fact in the source that owns it, scoped to that listing. Write a fleet-wide pattern once. |
| Over-silence | A completed `no_op` where a reply had value | Narrow the silence rule. Define the useful replies beside it. |
| Wrong owner | A neighboring Conduit skill loaded | Give the intent one owner; add exclusions to both descriptions. |
| Skipped step | The right skill loaded but a required tool wasn't called | Move the precondition into the tool or backend. Add a trace assertion. |
| Missing capability | The answer needed live data or an action | Build a tool backed by your system. |
| Tool contract | Wrong parameters, a default used, an overclaiming result | Fix parameter text, enums, defaults and the result `message`. |
| Missing context | Unlinked contact, null message ID, truncated thread | Resolve on the server; fail closed; fix linking or routing. |
| False or unsafe claim | Invented action, wrong listing, leak | Guardrail plus a backend check. |
| Escalation rule or urgent tag | `disposition_reason` names a rule, or Insights shows "Urgent tagged" | Narrow the rule or tag in Behavior, or keep it if the operator wants a person there. Escalation rules are read in the app; ask the operator for them. |
| Attachment | A video or file the agent can't read | Nothing to fix in instructions. Make sure a person sees these fast. |
| Wrong language | A reply in a language the guest didn't write in | Behavior: `response_language` (`Original` answers in the guest's language). |
| Must stay human | Refund decisions, disputes, legal | An urgent tag or handoff route, not more instructions. |
| Never ran | No run record | Section 8. |
| Another sender | A workflow, scheduled, PMS, portal or template message gave a wrong or confusing fact, or the guest is replying to one | Fix that sender's text, then make knowledge agree ([Knowledge](knowledge.md), section 9). |
| Person or process | The reply was right, but the home wasn't ready, a lock was offline, a code wasn't set, a teammate didn't follow up, a vendor didn't come, an owner changed something | Not an agent fix. List it for the operator with conversation IDs and evidence (device history, task records). Change the agent only if it made a promise the process couldn't keep. |

## 4. The fix log

Keep one log in the operator's working folder, one line per fix: date, cause class, layer, object changed, listings affected, the conversation IDs that led to it, and the result you expect.

On each run, count new cases in each logged class since the fix date. A class that came back means the fix was incomplete, landed in the wrong layer, or wasn't live. Read the new cases before fixing again. Conduit's own docs warn that an issue marked resolved without a test comes back the next month.

## 5. Conduit's own views

- **Escalations tab.** Conduit groups escalations into issues, each with an AI write-up, a category (for example Missing Info), recommendations and a conversation count. Use them as a starting map. They have no API, so ask the operator to share the top pending issues. Read two or three conversations behind an issue before acting: the grouping is AI generated. "Mark as resolved" records a decision, not a working fix.
- **Insights** shows escalation types: urgent tagged, AI needs your help, AI missing info, and message has attachments. Map them to the causes in section 3.
- **Operator** and "Fix with Operator" change configuration inside the app. If the operator used them, read back what changed before you build on it.

## 6. Practices from one operator's improvement

The operator's Conduit automation rate went from 41% (November 2025) to 92% (October 2026); the causes weren't independently measured. Treat these as hypotheses to test with your own numbers.

**Behind the first jump**
- **Knowledge from operations, scoped per listing.** The first build took one day. It used the field team's property-notes sheet, the spare-key tracker and owner walkthroughs. Chat history was weak: most homes yielded zero or one durable fact.
- **Conduit skills for the most frequent human cases first.** The lockout skill did the most:
  1. Check whether the guest's code is active yet.
  2. Try the main code, then the backup code.
  3. Offer the home's last-resort code, from a gated tool that checks the guest and stay.
  4. Direct the guest to the physical spare.
  5. Hand off only after all of these fail.

  The last-resort code opens only that home; never one that opens other homes or staff areas. Night lockouts then resolved without a person.
- **An owner-run week.** The owner answered every escalation personally and fixed each repeat. The reported rate reached about 90% within three days.
- **Physical work moved off the guest agent.** An operations agent dispatched field work, so the guest agent could answer while someone else owned the repair.

**Later work that kept the rate up**
- **Live tools instead of handoffs.** Early check-in and late checkout eligibility with atomic recording, quotes, payment and receipt status, and related stays.
- **Reversing over-silence.** Confirmations, consent, goodbyes and the last word came back after a strict silence rule suppressed them.
- **Natural wording.** Scripted replies read as "AI" to guests and reviewers. Coverage rules with fresh wording fixed it.

## 7. Trust ladder

Move toward autopilot in narrow expansions.

1. **Shadow or copilot.** The agent drafts and people send. Compare drafts with what people sent: better, worse, tie, both bad. Show full traces and a tool-errors view. Don't count another agent's replies as answers.
2. **Gate by message type.** Track how often people send a draft unchanged (`proposal_outcome`: approved, edited, dismissed) for each type: Wi-Fi, check-in, parking, early check-in. Promote a type once it clears an agreed bar, for example 95% approved unchanged over its last 50 drafts.
3. **Narrow autopilot.** Start with the cleared types, one cohort of homes or one inbox. `autopilot_schedule` limits hours; outside them Conduit falls back to copilot.
4. **Gates per step.** No double replies, no failed sends, median first reply in minutes, a small share waiting over 2 hours, a flat "came back" share, zero unsupported claims in a read sample. Keep a one-command rollback.
5. **Expand.** For example 25% → 50% → 75% → 100% of homes.

Routing moves contacts on new bookings only. Move existing contacts deliberately, and check contacts that hold stays in more than one brand.

## 8. Never ran versus chose silence

**No run record.** Check each of these:

- the listing is inactive in Conduit (`GET /v1/listings/catalog`, `active`; runs are suppressed without notice);
- the channel connection needs reconnecting (connection health may not appear in the API, so report it);
- the inbox has no enabled message trigger, the trigger scope excludes it, or a second agent listens to the same inbox;
- a routing filter evaluated false;
- the contact merged into another conversation;
- AI is paused for the contact (`ai_paused` on the conversation);
- the agent's `operation_mode` or schedule;
- an urgent tag or escalation rule;
- the guest called instead: voice agents are separate (MCP `list_voice_agents`) and calls are at `GET /v1/calls`.

**A run with `no_op` or `escalated`.** Read `disposition_reason`. Find the instruction, guardrail, escalation rule or tool result that produced it.
