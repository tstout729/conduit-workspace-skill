# Conduit workspace skill

**Raise your [Conduit](https://conduit.ai) AI automation rate with Claude Code or Codex.**

I run a vacation rental management company. In November 2025, our Conduit automation rate was 41%. In October 2026, it was 92%. I got there with Claude Code and Codex, one fix at a time. This skill is the method, written down so your coding agent can use it in your Conduit workspace.

It works in [Claude Code](https://claude.com/claude-code), [Codex](https://openai.com/codex) and any agent that supports [Agent Skills](https://agentskills.io).

## What it does

Ask your agent to set up Conduit, raise the automation rate, or find out why the AI answered wrong, stayed silent or escalated. The skill loads and gives the agent a method:

1. **A loop, not a one-time setup.** Measure the automation rate. Collect every conversation a person still handled. Find the cause of each one. Fix the biggest group first. Replay those cases as tests. Ship, then measure again.
2. **Each fix in the layer that owns it.**

   | Symptom | Fix it in |
   | --- | --- |
   | A fact was wrong or missing | Knowledge |
   | The facts were right, but the voice was wrong | Persona |
   | A leak, a false claim or an unsafe answer | Guardrail, or a mode or tag |
   | A step was skipped or the wrong process ran | Conduit skill |
   | The agent needed live data or an action | Tool and its backend |
   | The agent never ran | Runtime: mode, triggers, routing |

3. **Four modes.** *Raise automation* runs the loop. *Build* sets up a new agent, knowledge first, and starts it in copilot mode. *Fix one bad answer* traces a single reply back to its cause. *Audit* reads everything and changes nothing.
4. **Safety rules in every mode.** Your own rules come first. Take a snapshot before any change and read it back after. Never bulk-delete knowledge. Keep access codes out of prompts and serve them through a tool that checks the guest, the stay and the time. Test that the agent still replies when it should.
5. **A plain report.** What changed and why, the numbers before and after, the tests, and how to roll back.

It also covers what the Conduit API documentation doesn't put in one place: where `PATCH` replaces a whole list, why the simulator's `no_op` looks like a pass, which metric counts answer-and-escalate as automation, and how to list every knowledge article.

## Install

**Claude Code**, as a plugin:

```
/plugin marketplace add tstout729/conduit-workspace-skill
/plugin install conduit-workspace@conduit-workspace-skill
```

**Any agent** (Claude Code, Codex, Cursor and [many more](https://github.com/vercel-labs/skills)), with the skills CLI:

```sh
npx skills add tstout729/conduit-workspace-skill -g
```

**By hand**: copy or link the `skills/conduit-workspace` folder into your agent's skills folder, such as `~/.claude/skills/` for Claude Code or `~/.agents/skills/` for Codex.

```sh
git clone https://github.com/tstout729/conduit-workspace-skill
ln -s "$PWD/conduit-workspace-skill/skills/conduit-workspace" ~/.claude/skills/conduit-workspace
```

### Connect it to Conduit

The agent works through Conduit's MCP server or REST API, never the web app. Add the MCP server (it signs in with OAuth):

```sh
# Claude Code
claude mcp add --transport http --scope user conduit https://api.conduit.ai/v1/mcp

# Codex
codex mcp add conduit --url https://api.conduit.ai/v1/mcp
codex mcp login --scopes mcp:read,mcp:write,offline_access conduit
```

For the bundled scripts, make an API token in Conduit under **Settings > API & MCP** and set it in your shell. The scripts never print it.

```sh
export CONDUIT_API_TOKEN=capi_...
```

The scripts need only Python 3.9 or later. They have no other dependencies.

## Use it

Just ask:

- *"Audit our Conduit workspace. Change nothing. Tell me why automation is stuck."*
- *"Raise our Conduit automation rate. Start with the last 30 days."*
- *"A guest asked about parking and the AI said it would check. Find out why and fix it."*
- *"Set up a Conduit agent for our new mountain listings."*

The agent asks before any live change, snapshots what it will touch, and reports what it did in plain language.

## What's inside

| Path | What it is |
| --- | --- |
| [`SKILL.md`](skills/conduit-workspace/SKILL.md) | The rules, the layer table, the four modes, gotchas and the report format |
| [`references/automation-loop.md`](skills/conduit-workspace/references/automation-loop.md) | Measuring automation honestly, the loop, the trust ladder from copilot to autopilot |
| [`references/knowledge.md`](skills/conduit-workspace/references/knowledge.md) | Building, auditing and editing knowledge, and access details |
| [`references/persona-and-guardrails.md`](skills/conduit-workspace/references/persona-and-guardrails.md) | Voice, guardrail format, silence rules, truthful claims |
| [`references/skills-and-tools.md`](skills/conduit-workspace/references/skills-and-tools.md) | Conduit skills, custom tools and their backend contracts, workflows |
| [`references/api-and-testing.md`](skills/conduit-workspace/references/api-and-testing.md) | Endpoints, write traps, simulator limits, a regression harness |
| [`scripts/conduit_snapshot.py`](skills/conduit-workspace/scripts/conduit_snapshot.py) | A read-only snapshot of agents, Conduit skills, tools, connections and knowledge, with a completeness manifest |
| [`scripts/conduit_lint.py`](skills/conduit-workspace/scripts/conduit_lint.py) | Offline checks of a snapshot: shared objects, broken connections, unresolved `@` references, codes in prompt text (reported by location, never by value) |

The tests in [`tests/`](tests/) run offline, without a Conduit token: `python3 -I -B tests/test_scripts.py`.

## About the numbers

The 41% and 92% are Conduit's own automation rate for our workspace (`GET /v1/insights/automation_rate`), for November 2025 and October 1–16, 2026. That metric counts a reply the AI sent and then escalated as automated. Conduit's stricter fully autonomous rate is lower. The skill teaches your agent to report both, so you know which one you're improving.

## License

[MIT](LICENSE). Not affiliated with or endorsed by Conduit. Conduit is a trademark of its owner.
