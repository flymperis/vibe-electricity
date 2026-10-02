import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp(prefix="vibe-electricity-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SYNC_ON_STARTUP"] = "false"
os.environ["PAPERLESS_URL"] = "http://paperless.invalid"
os.environ["PAPERLESS_TOKEN"] = "test"
os.environ["OLLAMA_URL"] = ""
os.environ["WEBHOOK_SECRET"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")


@pytest.fixture
def db():
    from vibe_electricity.db import Base, engine, init_db

    init_db()
    yield
    Base.metadata.drop_all(engine)


class FakePaperless:
    """Stands in for the Paperless client: documents are {id: (title, content, checksum)}."""

    def __init__(self, docs: dict[int, tuple[str, str, str]], tag: str = "Electricity"):
        self.docs = docs
        self.tag = tag

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def close(self):
        pass

    def tag_id(self, name):
        return 7 if name == self.tag else None

    def tagged_documents(self, tag_id):
        return [{"id": i, "title": t, "modified": "2026-01-01T00:00:00Z", "tags": [7]} for i, (t, _, _) in self.docs.items()]

    def document(self, doc_id):
        t, content, _ = self.docs[doc_id]
        return {"id": doc_id, "title": t, "content": content, "modified": "2026-01-01T00:00:00Z"}

    def checksum(self, doc_id):
        return self.docs[doc_id][2]

    def ping(self):
        return {}
