Weekly docs check of Vozonda/vozonda (main). Follow AGENTS.md.

Compare README.md, docs/quickstart.md, docs/deployment.md, docs/architecture.md, CONTRIBUTING.md
and the CHANGELOG "Unreleased" section against the code: commands that no longer work, env
variables that do not exist (grep `env("` in apps/api), ports, default values, endpoints, screenshots
described but changed, features in the code that the CHANGELOG does not mention.
Fix only what you verified in the code, on branch `claude/docs-<yyyy-mm-dd>`, one PR listing each
fix with the code reference. If everything matches, do nothing.
