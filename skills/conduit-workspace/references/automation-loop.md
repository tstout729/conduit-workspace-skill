# Automation loop

Read this to measure automation, run the improvement loop, earn autopilot, or diagnose a run that never happened.

Contents: 1. Measure · 2. The loop · 3. Cause → layer · 4. Practices from one operator's improvement · 5. Trust ladder · 6. Never ran versus chose silence

## 1. Measure

Write down the definition and window before you pull numbers.

| Measure | Source | Notes |
| --- | --- | --- |
| AI-sent share | `GET /v1/insights/automation_rate?workspace_id&start_date&end_date[&category_name]` | Sent decisions ÷ countable decisions. Answer-and-escalate counts as sent. Window ≤ 90 days. |
| Handled alone | `GET /v1/insights/resolution_rate`, field `fully_autonomous` | Resolved, sent, no teammate message, no escalation. Report it with its denominator: eligible autopilot threads only, excluding `no_op`, copilot, inactive and unlinked runs. |
| Unanswered | Your own query over conversations | Latest guest message with no reply after 15 minutes and after 2 hours. |
| Human outbound share | Outbound messages attributed to teammates | `is_sent_by_autopilot: false` also covers inbound, workflow and other automated sends; separate them. Don't infer from `sender.user_id`. |
| Human work off-thread | Your operations records | Staff actions the conversation never shows (calls, visits, refunds). |
| Quality | A read sample of sent replies | Unsupported claims, wrong listing, internal language, double replies, guest had to repeat. |

- Insights endpoints allow about 10 requests per minute. Record `formula_version` and compare it before comparing periods.
- `no_op` counts, `autopilot_sent` (null means "not counted", not false) and test pass counts are not automation measures.
- A correct silent turn lowers the AI-sent share. Never chase the number with holding replies or by removing legitimate silence.

## 2. The loop

Run it daily during a push and weekly after.

1. **Collect.** Gather the window's failures from four places:
   - pending escalations (`GET /v1/escalations`);
   - runs with `escalated`, `unresolved` or `no_op` dispositions (`GET /v1/agents/{id}/runs`);
   - threads with a teammate message;
   - replies that went out but didn't get the outcome the operator intended: the guest asked again, a promise nobody kept, a wrong answer;
   - anything the operator flagged.
2. **Read.** Read each full thread and its run (`GET /v1/agents/{id}/runs/{run_id}`): skills loaded, tool calls and results, sources, guardrails, `disposition_reason`.
3. **Classify.** Name the cause with the table in section 3. Tally by cause. Fix the largest class first.
4. **Fill the facts.** For a missing or wrong fact, search the operator's own sources first ([Knowledge](knowledge.md), section 1). Ask the operator, in one short list, for what no source answers.
5. **Fix the class.** Change the owning layer for every listing and scenario the cause affects, not the one thread. Then make every other layer agree with it.
6. **Test.** Replay the cases, their neighboring scenarios and the reply-value cases ([API and testing](api-and-testing.md)).
7. **Ship.** Apply, read back, sample the next real runs and remeasure.
8. **Record.** Save the rule once, where the operator keeps rules.

The highest-yield habit: during the push, one person who knows the homes handles every escalated conversation. Each repeat becomes a knowledge fact, a Conduit skill change or a tool the same day.

## 3. Cause → layer

| Cause | What the trace shows | Fix |
| --- | --- | --- |
| Missing or wrong fact | No relevant source, a weak match, or a wrong value | Add or correct the fact in that listing's knowledge. Write a fleet-wide pattern once. |
| Over-silence | A completed `no_op` where a reply had value | Narrow the silence rule. Define the useful replies beside it. |
| Wrong owner | A neighboring Conduit skill loaded | Give the intent one owner; add exclusions to both descriptions. |
| Skipped step | The right skill loaded but a required tool wasn't called | Move the precondition into the tool or backend. Add a trace assertion. |
| Missing capability | The answer needed live data or an action | Build a tool backed by your system. |
| Tool contract | Wrong parameters, a default used, an overclaiming result | Fix parameter text, enums, defaults and the result `message`. |
| Missing context | Unlinked contact, null message ID, truncated thread | Resolve on the server; fail closed; fix linking or routing. |
| False or unsafe claim | Invented action, wrong listing, leak | Guardrail plus a backend check. |
| Must stay human | Refund decisions, disputes, legal | An urgent tag or handoff route, not more instructions. |
| Never ran | No run record | Section 6. |

## 4. Practices from one operator's improvement

The operator reported about 50% before and over 90% after; neither figure was independently measured. Treat these as hypotheses to test with your own numbers.

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

## 5. Trust ladder

Move toward autopilot in narrow expansions.

1. **Shadow or copilot.** The agent drafts and people send. Compare drafts with what people sent: better, worse, tie, both bad. Show full traces and a tool-errors view. Don't count another agent's replies as answers.
2. **Gate by message type.** Track how often people send a draft unchanged (`proposal_outcome`) for each type: Wi-Fi, check-in, parking, early check-in. Promote a type once it clears an agreed bar, for example 95% unchanged over its last 50 drafts.
3. **Narrow autopilot.** Start with the cleared types, one cohort of homes or one inbox. `autopilot_schedule` limits hours; outside them Conduit falls back to copilot.
4. **Gates per step.** No double replies, no failed sends, median first reply in minutes, a small share waiting over 2 hours, zero unsupported claims in a read sample. Keep a one-command rollback.
5. **Expand.** For example 25% → 50% → 75% → 100% of homes.

Routing moves contacts on new bookings only. Move existing contacts deliberately, and check contacts that hold stays in more than one brand.

## 6. Never ran versus chose silence

**No run record.** Check each of these:

- the listing is inactive in Conduit (runs are suppressed without notice);
- the channel connection needs reconnecting (connection health may not appear in the API, so report it);
- the inbox has no message trigger, or the trigger scope excludes it;
- a routing filter evaluated false;
- the contact merged into another conversation;
- AI is paused for the contact;
- the agent's `operation_mode` or schedule;
- an urgent tag.

**A run with `no_op` or `escalated`.** Read `disposition_reason`. Find the instruction, guardrail or tool result that produced it.
