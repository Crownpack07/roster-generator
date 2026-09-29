"""The FastAPI application.

`create_app` accepts a database and a runner so tests can pass mongomock and
inline executors. In production both are None and the lifespan handler builds
the real ones: one MongoClient, because Atlas M0 caps connections, and one
process pool.

Routes that touch MongoDB are declared `def`, not `async def`, so FastAPI
runs them in its threadpool and the synchronous driver never blocks the event
loop.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from roster.api.routers import auth
from roster.jobs.runner import SolveRunner
from roster.store.client import get_database, make_client
from roster.store.config import Settings, settings_from_env
from roster.store.indexes import ensure_indexes


def create_app(
    *,
    settings: Settings | None = None,
    db=None,
    runner: SolveRunner | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved = settings if settings is not None else settings_from_env()
        app.state.settings = resolved

        client = None
        if db is not None:
            app.state.db = db
        else:
            client = make_client(resolved)
            app.state.db = get_database(client, resolved)
        ensure_indexes(app.state.db)

        app.state.runner = runner or SolveRunner(
            app.state.db,
            time_limit_s=resolved.solve_time_limit_s,
            max_workers=resolved.solve_max_workers,
        )
        app.state.runner.start()
        try:
            yield
        finally:
            app.state.runner.shutdown()
            if client is not None:
                client.close()

    app = FastAPI(title="Roster", lifespan=lifespan)
    app.include_router(auth.router)
    return app
