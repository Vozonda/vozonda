Weekly health check of Vozonda/vozonda (main). Follow AGENTS.md.

1. Dependencies: `uv lock --upgrade --dry-run` style check of apps/api and `npm outdated` /
   `npm audit --omit=dev` in apps/web. Known vulnerabilities first.
2. Tests: run the full API suite three times; list any test that is not green every time (flaky).
3. Warnings: ruff (full repo scripts too), svelte-check warnings, Python DeprecationWarnings in the
   test output.
4. If there are safe fixes (patch/minor updates without API changes, a flaky test with a clear
   cause), make them on branch `claude/health-<yyyy-mm-dd>`, run all checks, open ONE PR.
5. Everything else goes into ONE issue titled `health <yyyy-mm-dd>` with a short table:
   item, severity, proposed action. If nothing is worth reporting, do nothing.
