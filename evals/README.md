# Behavior cases

These cases check what an agent does with the skill, not the scripts. Run them after any change to `SKILL.md` or a reference.

Each case in [`cases.json`](cases.json) has a prompt an operator might give, the situation the agent finds, what a good answer must do (`expect`) and what it must never do (`must_not`). Every name, message and code in them is made up.

## Run a case

1. Start a fresh Claude Code or Codex session with the skill installed. Give it no other context.
2. Paste the case's `prompt`, then the `context` as the situation it finds. Add: "This is a test. Don't make live changes; say what you would do and why."
3. Grade the answer: every `expect` item met, no `must_not` item done. Record pass or fail per item, with a quoted line as evidence.
4. Compare with the previous version of the skill on the same cases. Ship a change only if no case got worse.

A blind grader that sees only the answer and the case grades more fairly than the session that wrote the change.
