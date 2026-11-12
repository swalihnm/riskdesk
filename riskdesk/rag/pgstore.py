"""pgvector store for the knowledge-base chunks (dense retrieval in PostgreSQL).

Same embeddings as the in-memory dense index (all-MiniLM-L6-v2). The table is rebuilt from the chunks each time
it is loaded, so it always matches the knowledge base on disk.

Connection: RISKDESK_PG_DSN, default postgresql://riskdesk:riskdesk_local_only@localhost:5432/riskdesk
(the credentials are from docker-compose.yml and are for local use only).
"""

from __future__ import annotations

import os

import numpy as np

from riskdesk.rag.index import DENSE_MODEL, dense_embed

DSN = os.environ.get("RISKDESK_PG_DSN", "postgresql://riskdesk:riskdesk_local_only@localhost:5432/riskdesk")
DIM = 384
TABLE = "kb_chunks"


def _connect():
    import psycopg
    return psycopg.connect(DSN, autocommit=True)


def available() -> bool:
    try:
        with _connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def _vec(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


def load(chunks) -> int:
    """Rebuild the table from the given chunks. Returns the number of rows written."""
    texts = [c.text for c in chunks]
    emb = dense_embed(texts)
    with _connect() as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(f"DROP TABLE IF EXISTS {TABLE}")
        conn.execute(f"""CREATE TABLE {TABLE} (
            id TEXT PRIMARY KEY, section_id TEXT NOT NULL, doc TEXT NOT NULL, heading TEXT NOT NULL,
            body TEXT NOT NULL, embedding VECTOR({DIM}) NOT NULL, model TEXT NOT NULL)""")
        with conn.cursor() as cur:
            for c, v in zip(chunks, emb):
                cur.execute(f"INSERT INTO {TABLE} VALUES (%s,%s,%s,%s,%s,%s::vector,%s)",
                            (c.id, c.section_id, c.doc, c.heading, c.text, _vec(v), DENSE_MODEL))
        conn.execute(f"CREATE INDEX ON {TABLE} USING hnsw (embedding vector_cosine_ops)")
    return len(chunks)


def search(query: str, k: int = 5) -> list[dict]:
    """Top-k distinct sections by cosine distance, best first. Exact on small tables; HNSW for larger ones."""
    q = _vec(dense_embed([query])[0])
    out, seen = [], []
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT id, section_id, heading, doc, body FROM {TABLE} "
            f"ORDER BY embedding <=> %s::vector LIMIT 50", (q,)).fetchall()
    for cid, sid, heading, doc, body in rows:
        if sid in seen:
            continue
        seen.append(sid)
        out.append({"id": sid, "chunk_id": cid, "heading": heading, "doc": doc, "text": body, "rank": len(seen)})
        if len(out) == k:
            break
    return out


class PgIndex:
    """Adapter with the same search() interface as HybridIndex, so evaluate() works on it unchanged."""

    def search(self, query: str, k: int = 5) -> list[dict]:
        return search(query, k)
