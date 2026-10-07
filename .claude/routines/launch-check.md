Launch readiness check of Vozonda/vozonda (main), until the repo is public. Follow AGENTS.md.

Check and report, each with pass/fail and evidence:
1. `python3 scripts/public_scan.py` passes; no private hosts, paths, names, secrets.
2. The Docker quickstart in docs/quickstart.md: `docker compose config` is valid, Dockerfiles build
   (CPU only), the documented commands exist.
3. README: every link and anchor resolves; images exist.
4. LICENSE and THIRD_PARTY_NOTICES.md cover every dependency in uv.lock and package-lock.json.
5. CI on main is green; open issues labelled `launch`.
Keep ONE issue titled `launch readiness` up to date (edit its body, add a comment with the date and
what changed). Do not open a new one each time. Do not change code in this routine.
