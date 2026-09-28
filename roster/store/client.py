"""The single MongoClient.

Atlas M0 caps connections, so exactly one client is created (in the FastAPI
lifespan handler) and reused for the process's lifetime.
"""

from __future__ import annotations

from pymongo import MongoClient
from pymongo.database import Database

from roster.store.config import Settings


def make_client(settings: Settings) -> MongoClient:
    return MongoClient(settings.mongodb_uri, tz_aware=True)


def get_database(client: MongoClient, settings: Settings) -> Database:
    return client[settings.mongodb_db]
