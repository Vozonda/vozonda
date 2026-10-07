You work on the Vozonda repo (GitHub Vozonda/vozonda). Follow AGENTS.md, especially "Cloud agents and GitHub".

Task: implement the GitHub issue that triggered this run (it has the label `agent`).
1. Read the issue and every comment. If it is unclear, too large for one PR, or needs a GPU or a
   real voice/LLM run to verify, do not guess: comment on the issue with the open questions or a
   proposed split, and stop.
2. Branch `agent/issue-<number>-<short-topic>`. Make the smallest change that meets the issue.
   Add or update tests that fail without your change.
3. Run the checks from AGENTS.md (ruff, pytest, svelte-check, build, public_scan). All must pass.
4. Open a PR: title `<scope>: <verb> <object>`, body = what changed, why, how it was tested (paste
   the result lines), what could not be checked in the cloud, `Closes #<number>`.
5. Comment on the issue with the PR link. Never merge.
