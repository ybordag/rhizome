from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.models import Base
from tests.support.factories import make_profile
from tests.support.fakes import FakeBoundModel
from tests.support.patching import build_test_agent, patch_all_sessionlocals


@pytest.fixture
def test_engine(tmp_path):
    db_path = tmp_path / "test_rhizome.db"
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def setup_schema(test_engine):
    Base.metadata.create_all(test_engine)
    try:
        yield
    finally:
        Base.metadata.drop_all(test_engine)


@pytest.fixture
def session_factory(test_engine, setup_schema):
    return sessionmaker(bind=test_engine)


@pytest.fixture
def db_session(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def patched_sessionlocal(monkeypatch, session_factory):
    patch_all_sessionlocals(monkeypatch, session_factory)
    return session_factory


@pytest.fixture
def test_checkpointer(tmp_path):
    checkpoint_path = tmp_path / "test_checkpoints.db"
    conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
    try:
        yield SqliteSaver(conn)
    finally:
        conn.close()


@pytest.fixture
def fake_bound_model():
    return FakeBoundModel()


@pytest.fixture
def fresh_test_graph(monkeypatch, session_factory, test_checkpointer, fake_bound_model):
    return build_test_agent(monkeypatch, fake_bound_model, session_factory, test_checkpointer)


@pytest.fixture
def seed_garden_profile(db_session, patched_sessionlocal):
    return make_profile(db_session)
