# Routines (cloud agents)

Each file is the prompt of one routine. The maintainer only decides (merge yes/no); routines
never push to `main`. Rules for every run: see `AGENTS.md`, section "Cloud agents and GitHub".

| File | Trigger | Output |
|---|---|---|
| `issue-to-pr.md` | an issue gets the label `agent` | a PR that closes the issue |
| `external-pr-review.md` | a PR opened by someone outside the org | a review comment |

Only work with real value runs here. Dependency and security alerts come from GitHub itself;
docs are updated in the PR that changes the code.
