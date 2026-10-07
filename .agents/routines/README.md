# Routines (cloud agents)

Each file is the prompt of one routine. The maintainer only decides (merge yes/no); routines
never push to `main`. Rules for every run: see `AGENTS.md`, section "Cloud agents and GitHub".

| File | Trigger | Output |
|---|---|---|
| `issue-to-pr.md` | an issue gets the label `agent` | a PR that closes the issue |
| `external-pr-review.md` | a PR opened by someone outside the org | a review comment |
| `weekly-health.md` | Mondays 06:00 UTC | one PR (safe updates) and/or one issue |
| `docs-sync.md` | Wednesdays 06:00 UTC | one PR with doc fixes, or nothing |
| `launch-check.md` | Tuesdays and Fridays 06:00 UTC until launch | one status issue (updated, not duplicated) |
