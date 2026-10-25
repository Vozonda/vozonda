"""_run closes the job generator in its own task when it stops at done/failed/review.

run_job sets the LOCAL_ONLY context variable and resets it in a finally block. _run used to
break out of the generator and leave it suspended; the event loop finalized it later in
another context, where LOCAL_ONLY.reset(token) raised "ValueError: <Token ...> was created
in a different Context" after every render ("Task exception was never retrieved").
"""

import asyncio
import contextvars

from vozonda_api import main

FLAG: contextvars.ContextVar[bool] = contextvars.ContextVar("test_flag", default=False)


def test_generator_finally_runs_before_run_returns(monkeypatch):
    events: list[str] = []

    async def runner(store, job_id):
        token = FLAG.set(True)
        try:
            yield {"state": "done"}
            yield {"state": "never reached"}
        finally:
            FLAG.reset(token)          # raises in a foreign context
            events.append("closed")

    monkeypatch.setattr(main, "listeners", {})
    monkeypatch.setattr(main, "tasks", {})

    async def scenario():
        await main._run("t-close-1", runner=runner)
        events.append("run returned")

    asyncio.run(scenario())
    assert events == ["closed", "run returned"]
