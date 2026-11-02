# CLAUDE.md -- cancho-flow

Design before code: every verb gets a section in `docs/design.md` before its implementation, and every claim in it is either measured (with machine, conditions and the number of runs) or marked as a choice, a read (with the file it was read from), or open.

- **Agent-first, like cancho-ml, cancho-table and cancho-stats.** The CLI, errors and logs follow cancho `docs/agent-toolbox.md` through the `contract/` package of `cancho-tools`, pinned by commit and never copied. Errors are data with a stable `flow.<name>` rule tag, an exit code and, where safe, a repair. No payload is ever logged or recorded.
- **A record is a pure function of its inputs.** No timestamp, host name, process id, absolute path or payload in a record; the same step gives the same bytes. A feature that cannot keep that is refused or documented as the exception, with a test.
- **Authority is a fact.** Two binaries: `flow` (starts programs from one baked directory, holds a clock for the deadline only) and `flow-records` (reads only). `scripts/manifest.py --check` fails if a derived row differs from the committed one or exceeds the ceiling. Widening a row is an edit a person reviews.
- **No file over 2,000 lines. Every refusal has a rule tag. No input reaches a panic.**
- **Gates are written before the code they judge and must be able to fail.** Mutants: all killed, or each survivor explained.
- **Measured claims only.** A claim found false is corrected in place, in the document that made it. Never state a speed against another tool that was not measured here.
- **`flow` is not a scheduler, a shell or a sandbox, and a plan is data.** If a request needs more than a list of argument lists, the answer is "write a program and call `flow step`".
- Licence EUPL-1.2, copyright Alpibru S.L. Commit trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; PRs stay draft until the maintainer says merge; no force-push to main.
