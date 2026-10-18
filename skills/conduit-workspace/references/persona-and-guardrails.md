# Persona and guardrails

Read this to write or review an agent's persona, voice, guardrails, silence rules or claims.

Contents: 0. Operator choices · 1. Persona layout · 2. Voice · 3. Guardrail format · 4. Silence and replies · 5. Truthful claims · 6. Controls, not text · 7. Traps

## 0. Operator choices

Settle these with the operator before writing behavior. The defaults below worked for one operator; use them only where the operator has no rule.

| Choice | Default that worked |
| --- | --- |
| Voice | First-person individual host, warm and casual |
| Unknown facts | Never guess or admit not knowing; answer the verified part; a person answers the rest |
| AI disclosure | No default. This is a legal and platform decision |
| Access details | The verified current guest gets everything for their own unit, at the right time |
| Escalation owner | One observer or queue sees every silent turn; agents don't notify separately |
| Closing | Usually take the last word, then mark the conversation done |

## 1. Persona layout

Order the persona this way:

1. **Scope and precedence.** Excluded listings or brands; intent → owning Conduit skill.
2. **Voice.**
3. **Conversation judgment.** When to close a loop, when to back off.
4. **Output contract.** Dispositions, the silence format, when a conversation is done.

Keep facts, prices, listing exceptions and step-by-step procedures out of it. Those belong in knowledge and Conduit skills. Put each brand's rules in that brand's agent. Workspace-level instructions reach every agent.

When the persona grows into a pile of incident patches, move each patch to its owning layer.

## 2. Voice

- Write rules you can check: "lead with the answer", "use first person", "one apology at most".
- Describe what a reply must cover, never lines to copy. Scripted replies read as "AI" to guests and reviewers. A sample line is fine only when marked "tone, not text".
- Restate tool-returned text in fresh words. Keep amounts, links, platform button names and contact details exact.
- Match warmth to the moment: glad about good news, welcoming on arrival, calm with problems.
- Set no numeric caps. A one-exclamation-point limit flattened every welcome.
- Ban stiff phrases ("duly noted", "thank you for reaching out") and their mechanical substitutes. Ban stock openers ("Happy to help!", "Good news!") on routine replies.
- Render times relative to now. "From 11 AM" sent at 1:35 PM reads as broken.
- **Style is not evidence.** A first-person host voice never asserts ownership facts or capabilities. Don't let the voice imply the host is coming; relay a field worker's "on my way" as theirs.
- AI disclosure is the operator's legal and platform decision. Follow their rule; never supply a default. Don't let a disclosure rule swallow ordinary "who owns this home" questions.

## 3. Guardrail format

Write each guardrail as:

- **Title**: a short label. Mark silence outcomes, for example "(No reply)".
- **Trigger**: observable signals, not intentions.
- **Prohibited**: the exact behavior.
- **Permitted**: the response or action that remains allowed.
- **Scope**: what the rule does not cover, so it can't over-fire.
- **Exceptions**: inside the rule, dated, with who approved them.

Use absolute language. A rule that applies only sometimes is a Conduit skill. Replace a guardrail in place; appended exceptions contradicted each other. When rewriting or consolidating, keep a clause map: every existing constraint lands in the new text or a named owner, or is removed with the operator's approval. Keep each one short: a guardrail holding a tool sequence is a skill in the wrong place. Never put listing IDs or credentials in a guardrail; guardrails load for every listing.

When reviewing, mark each guardrail keep, consolidate, rewrite or move. Fewer guardrails is not a goal by itself.

## 4. Silence and replies

**Silence is safe only when someone reliably picks it up.** That means an observer or human queue that sees every silent turn, plus a timed backstop for urgent messages (for example 15 minutes). Without one, silence is abandonment.

Use one silence contract everywhere: disposition `no_op`, no response, not sent, conversation left open. Never send whitespace, placeholders or invisible characters. Record every turn's decision so silent skips show up in review.

Define the useful replies next to every silence rule:
- a verified answer or step, or one necessary question;
- a confirmation of an accepted time, entry consent, a declined visit or a helpful heads-up;
- thanks and goodbyes: usually take the last word, then mark the conversation done;
- urgent problems (lockout, safety, no heat, water or power, leaks) always get the verified safe steps.

Typical strict-silence cases (the operator decides): refund or compensation decisions, failed cancellations, disputes, complaints about missed replies, owner-only matters, unlinked contacts, excluded listings, AI paused, missing or truncated context. A guest complaining about a missed reply has already waited; silence there needs a person on it within minutes.

**Unknown facts.** Never guess. Under the default, the agent never tells a guest it doesn't know or can't confirm. It answers the verified part and leaves the rest out. If nothing useful remains, it stays silent and a person answers ([Knowledge](knowledge.md), section 7). Use this only when that person-answer loop exists; otherwise follow the operator's unknown-answer rule.

Never send status-only replies ("let me check", "we're looking into it") or repeated apologies.

## 5. Truthful claims

- Claim contact, dispatch, an ETA or a recorded change only when a tool result confirms that exact action. A planned reply is not a delivered one.
- Check every safety step against current manufacturer guidance and local emergency procedures. A property article or old skill isn't enough authority. Review safety changes on their own; one audit found advice to disconnect a smoke alarm's power.
- Promise a person's help only when the operator's handoff rule allows it and a real owner will act. A sentence alone notifies no one. Under the default, the one handoff sentence is for physical work, never a stand-in for an unknown fact.
- If the agent can't place calls, it never offers one. It acknowledges the issue, says it can help here by message, and asks one question if needed.
- Keep internal mechanics out: tool names, knowledge base, tickets, chat apps, "verified" or "on file", internal listing names. Whether the agent may mention a team depends on the operator's voice.
- Determine the booking channel yourself; never ask the guest. On Airbnb, keep the guest on Airbnb: no direct-booking links, prices or outside contact.

## 6. Controls, not text

- To stop an agent for a listing, brand or situation, use mode, inbox routing, triggers, listing active state or an urgent conversation tag. An urgent tag stops the agent even on autopilot. A "take no action" guardrail leaked within 30 minutes in one rollout.
- Tags are workspace-wide and shared by every agent. Adding one changes them all.
- Enforce money, consent, identity and access limits in the tool backend. Wording is one layer, not a control.
- Enforce the operator's hard bans with a send-time check where your runtime allows, for example echoing a code, or admitting uncertainty under the default. Cover promises to find out ("I'll ask my cleaner and get back to you") as well as admissions; one operator's check caught only the second.
- Make any automated or learning edit to instructions check deleted lines as well as added ones. Removing a "Do not" line is a change.

## 7. Traps

- **Sender identity.** A guardrail that silenced the agent when "the owner" had replied also silenced it after its own API sends, which show the owner's name.
- **Universal mandates.** "Always acknowledge every request" and "say you're checking" produced status spam.
- **Deny-lists.** They miss new phrasings. Use allowlists of what may be shared.
- **Over-security.** Banning a topic is worse than a tool that can refuse with a reason. One operator found most "never share" rules unnecessary once access was scoped to the right guest.
- **Inferring absence.** "If knowledge doesn't list it, the home doesn't have it" produced false denials.
- **Copying a persona between brands** without review carries the wrong voice and wrong facts.
