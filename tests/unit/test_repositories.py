"""Run the shared repository contract suite against the in-memory backend."""

from __future__ import annotations

import pytest

from app.repositories.base import Repository
from app.repositories.memory import InMemoryRepository
from tests.repositories.contract import RepositoryContract


class TestInMemoryRepository(RepositoryContract):
    @pytest.fixture
    def repository(self) -> Repository:
        return InMemoryRepository()
