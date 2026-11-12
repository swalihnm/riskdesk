"""pgvector backend tests. Skipped automatically when the Postgres container is not reachable.

The check that matters: the database returns the same top sections as the in-memory dense index for every
labelled question, so the database adds storage and not a different retrieval result."""

import json
import os

import pytest

from riskdesk.config import KB_DIR, RAG_V2_PATH
from riskdesk.rag import pgstore
from riskdesk.rag.index import HybridIndex, chunk_section

pytestmark = pytest.mark.skipif(not pgstore.available(), reason="Postgres with pgvector not reachable")


@pytest.fixture(scope="module")
def loaded():
    chunks = chunk_section(KB_DIR)
    n = pgstore.load(chunks)
    assert n == len(chunks)
    return chunks


def test_table_rows_match_chunks(loaded):
    import psycopg
    with psycopg.connect(pgstore.DSN, autocommit=True) as conn:
        (count,) = conn.execute(f"SELECT COUNT(*) FROM {pgstore.TABLE}").fetchone()
    assert count == len(loaded)


def test_database_top5_matches_in_memory_dense_index(loaded):
    qs = [json.loads(line) for line in open(RAG_V2_PATH, encoding="utf-8") if line.strip()]
    mem = HybridIndex(loaded, method="dense")
    disagreements = []
    for q in qs:
        a = [h["id"] for h in mem.search(q["q"], 5)]
        b = [h["id"] for h in pgstore.search(q["q"], 5)]
        if a != b:
            disagreements.append((q["q"], a, b))
    assert not disagreements, disagreements[:2]


def test_database_recall_at_5_on_paraphrased_set(loaded):
    from riskdesk.rag.index import evaluate
    qs = [json.loads(line) for line in open(RAG_V2_PATH, encoding="utf-8") if line.strip()]
    r = evaluate(pgstore.PgIndex(), qs, k=5)
    assert r["recall@5"] >= 0.9
