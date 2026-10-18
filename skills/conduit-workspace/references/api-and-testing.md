# API and testing

Read this before any live read beyond the bundled snapshot, any write, or any test of agent behavior.

Contents: 1. Access · 2. Endpoints · 3. Write semantics · 4. Snapshot, apply, read back · 5. Simulation limits · 6. Regression harness · 7. Test cases · 8. Rate limits

## 1. Access

- REST base: `https://api.conduit.ai/v1`, with `Authorization: Bearer <token>`. Most routes need `workspace_id`; list workspaces with `GET /v1/workspaces`.
- MCP: `https://api.conduit.ai/v1/mcp`. It may expose only `search_tools` and `call_tool`; discover the catalog each session. Some operations exist only in MCP.
- REST and MCP take different argument names for similar operations. One integration failed half its knowledge searches on a wrong argument name. Check each schema.
- Current references: `https://docs.conduit.ai/llms.txt` and `https://docs.conduit.ai/api-reference/openapi.json`.
- Product versions change field names and labels. Never write from memory.

## 2. Endpoints

| Object | Routes |
| --- | --- |
| Agents | `GET /v1/agents?workspace_id`, `GET/PATCH /v1/agents/{id}`. Persona is `instructions`; guardrails are `{id, title, knowledge}`. |
| Triggers | `GET/POST /v1/agents/{id}/triggers`, `PATCH/DELETE …/triggers/{trigger_id}` |
| Conduit skills | `GET/POST /v1/skills`, `GET/PATCH/DELETE /v1/skills/{id}`; body field is `body` |
| Tool access | `GET /v1/agents/{id}/tools`, `PATCH` with `{tool_name, source, enabled}` |
| Integration tools | `GET /v1/agents/{id}/connections` (not in the tools list) |
| Custom tools | `/v1/custom-tools`, `/v1/custom-tools/{id}`, `GET /v1/custom-tools/runtimes`, `POST …/{id}/run` |
| Knowledge | `POST /v1/kb/nodes/search` (inventory), `GET/PATCH/DELETE /v1/kb/nodes/{id}`, `POST /v1/kb/search` (semantic chunks) |
| Runs | `GET /v1/agents/{id}/runs`, `GET …/runs/{run_id}` |
| Testing | `POST /v1/agents/{id}/simulate`; `POST /v1/agents/{id}/run` is a real dispatch |
| Insights | `GET /v1/insights/automation_rate`, `GET /v1/insights/resolution_rate` |
| Escalations | `GET /v1/escalations?status=pending` |
| Workflows | `GET /v1/workspaces/{id}/workflows`, `GET /v1/workflows/schema` |

Lists use `limit` (up to 100) with `cursor`, returning `next_cursor` and `has_more`. Follow every page and stop on a repeated cursor. Adapters that stopped at page one silently missed records.

## 3. Write semantics

- Agent PATCH replaces `skill_ids` and `triggers` when sent. Send guardrails as the complete array with existing IDs, or use per-item MCP tools.
- `model: null` resets the model to the workspace default.
- `operation_mode` (`autopilot`, `copilot`, `inactive`) is separate from `enabled`. `auto_mark_as_done` changes what "done" means.
- A trigger PATCH replaces its whole `config`. `POST …/triggers` adds one without replacing the others.
- A per-agent tool disable has returned success without persisting. Read it back.
- A personal (user-scoped) connection on an agent runs on that person's credentials for everyone.
- Whether an API PATCH publishes at once or stages a version is undocumented. Read back the effective state.

## 4. Snapshot, apply, read back

1. **Snapshot.** Run `scripts/conduit_snapshot.py` into a new folder and confirm its manifest says complete. It doesn't export workflows, triggers outside agent records, or workspace instructions; fetch any of those you will change separately. Keep the folder private.
2. **Prepare.** Write the full before and after text or payload. Keep a manifest: object ID, field, expected previous hash, fields that must not change.
3. **Re-fetch.** Compare against the snapshot right before writing. If someone else changed it, reconcile instead of overwriting.
4. **Apply.** Make changes one at a time and journal each request and outcome. After an uncertain create, check for a duplicate before retrying.
5. **Read back.** Use an independent GET. Check the intended diff, then the protected fields: model, mode, triggers, other agents' tool access and skill lists.
6. **Roll back narrowly.** Restore only the fields you changed. Never restore a whole stale snapshot over newer work.

## 5. Simulation limits

`POST /v1/agents/{id}/simulate` takes `inbound_message`, `channel`, `history` and `timeout_ms`.

- It can't attach a contact, reservation or listing. An unlinked test usually ends `no_op`, which proves only the unlinked-contact rule.
- It uses the real clock. Use dates in the future.
- It promises not to message a contact. It may still run enabled tools for real; one operator saw writes persist.
- `would_send` describes autopilot only.
- Inspect `disposition`, `disposition_reason`, `trace.skills`, `trace.tool_calls`, `trace.sources` and `trace.guardrails`. Read the full response.

## 6. Regression harness

Use this when native behavior must be tested. Creating these objects is a write, so get authorization.

1. Create an inactive QA agent with no triggers. Copy in the candidate persona, guardrails and Conduit skills. Use the target's model only if the operator allows it.
2. Give it fixture tools, not production writes. Fixtures check their arguments and return production-shaped success, failure and unknown results.
3. Before the first run, read the QA agent's effective tools and connections. Globally enabled tools reach it too. Point tool and action-workflow mentions at fixtures, and skill mentions at the QA copies. Use synthetic listing and status context. If any production write is still reachable, stop and use an offline harness or a separate workspace. Never disable a shared global tool just to make a test safe.
4. Put the linked context (reservation, listing, prior turns) in a clearly labeled fixture block. This tests instruction logic, not context plumbing.
5. Assert per case:
   - `would_send` and disposition;
   - text that must appear and text that must not (internal words, "not sure", code values);
   - the owning Conduit skill loaded;
   - required and forbidden tool calls;
   - required and absent parameters.
6. Key each result to a hash of the configuration under test.
7. Read every reply in full. Many assertion failures turn out to be test bugs, and some passing replies still contain bad caveats.
8. Delete the QA objects afterward and confirm they're gone.

Then sample the next real runs after release.

## 7. Test cases

Cover replies as well as silence. An agent that suppresses everything fails. Derive each expectation from the operator's choices; the "must show" column below uses the defaults in [Persona and guardrails](persona-and-guardrails.md).

| Case | Must show |
| --- | --- |
| Guest accepts an offered time, gives entry consent, declines a visit | One natural confirmation; the record written first |
| "We just left", "thanks!" at checkout | A goodbye, conversation marked done |
| Ordinary house question with a known fact | The exact listing's fact, no internal words |
| Unknown fact | No admission, guess or search suggestion; silence if nothing else is useful |
| Known and unknown parts together | The known part answered |
| Item missing from a compact search result | A full-article check before any denial |
| Wrong listing, paired unit, retired duplicate | No borrowed facts or codes |
| Lockout | The access recovery path; codes only for that unit |
| Call request with a clear problem | The problem addressed by message; no callback offer |
| Refund dispute, failed cancellation, missed-reply complaint | Required silence, conversation open |
| Broad issue next to a specific owner (heating versus maintenance) | The specific owner loaded, its key question asked |
| Early check-in on arrival day versus days ahead | Live eligibility; no time the tool didn't give |
| Safety issue where an old article suggests an unsafe step | The unsafe step refused; current safe guidance given |
| Tool failure or unknown write | No success claim, no unsafe retry |
| Missing message ID or truncated thread | No invented ID; fail closed |
| Shared object used by a protected agent | The protected agent unchanged |
| Knowledge edit, then the next PMS sync | Facts and structure survive; no stale contradiction |

Use fabricated identities and placeholder credentials in fixtures. Never copy real guest records into a repository.

## 8. Rate limits

- REST and MCP share about 120 requests per minute per workspace. Live guest traffic draws from the same budget.
- Insights endpoints allow about 10 per minute.
- On 429, wait for `Retry-After`. Run bulk jobs in small batches behind guest replies.
- Don't retry a write without an idempotency key. Never retry a send that may have succeeded.
