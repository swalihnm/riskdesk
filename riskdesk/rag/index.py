"""Retrieval over the knowledge base.

Chunking strategies
- section: one chunk per '## ' section (the default; ids look like `limit_policy#hard-limits-and-warning-levels`)
- window:  overlapping fixed-size windows of words inside each section (for the chunking comparison)

Scoring methods
- bm25:      lexical BM25 (rank_bm25)
- dense:     sentence-transformers all-MiniLM-L6-v2 embeddings, cosine similarity (free, runs locally)
- hybrid:    reciprocal-rank fusion of bm25 and dense (the default used by the agents)
- charngram: hashed character-trigram vectors, kept only as an ablation baseline

Every result is collapsed to its source section, so relevance is judged at section level.
"""

from __future__ import annotations

import glob
import hashlib
import math
import os
import re
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi

DENSE_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DIM = 4096
RRF_K = 60
POOL = 50
_WORD = re.compile(r"[a-z0-9]+")
_embedder = None


@dataclass
class Chunk:
    id: str          # chunk id (for section chunks this is the section id)
    section_id: str  # the section this chunk came from
    doc: str
    heading: str
    text: str


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _sections(kb_dir: str) -> list[Chunk]:
    out: list[Chunk] = []
    for path in sorted(glob.glob(os.path.join(kb_dir, "*.md"))):
        doc = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for part in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
            heading, _, body = part.partition("\n")
            heading = heading.strip()
            sid = f"{doc}#{slug(heading)}"
            out.append(Chunk(id=sid, section_id=sid, doc=doc, heading=heading,
                             text=f"{heading}\n{body.strip()}"))
    return out


def load_chunks(kb_dir: str) -> list[Chunk]:
    """Section chunks (kept under the old name for existing callers)."""
    return _sections(kb_dir)


def chunk_section(kb_dir: str) -> list[Chunk]:
    return _sections(kb_dir)


def chunk_window(kb_dir: str, words: int = 60, overlap: int = 20) -> list[Chunk]:
    out: list[Chunk] = []
    for sec in _sections(kb_dir):
        toks = sec.text.split()
        step = max(words - overlap, 1)
        starts = list(range(0, max(len(toks) - overlap, 1), step)) or [0]
        for i, start in enumerate(starts):
            piece = " ".join(toks[start:start + words])
            out.append(Chunk(id=f"{sec.section_id}@{i}", section_id=sec.section_id, doc=sec.doc,
                             heading=sec.heading, text=piece))
    return out


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(DENSE_MODEL)
    return _embedder


def dense_embed(texts: list[str]) -> np.ndarray:
    return np.asarray(get_embedder().encode(texts, normalize_embeddings=True, batch_size=32))


def char_embed(text: str) -> np.ndarray:
    v = np.zeros(DIM)
    t = f" {' '.join(_tokens(text))} "
    for i in range(len(t) - 2):
        h = int(hashlib.md5(t[i:i + 3].encode()).hexdigest()[:8], 16) % DIM
        v[h] += 1.0
    n = np.linalg.norm(v)
    return v / n if n else v


class HybridIndex:
    """Retriever over a list of chunks. Default method is hybrid (BM25 + dense, fused by rank)."""

    METHODS = ("bm25", "dense", "hybrid", "charngram")

    def __init__(self, chunks: list[Chunk], method: str = "hybrid"):
        if method not in self.METHODS:
            raise ValueError(f"method must be one of {self.METHODS}")
        self.chunks = chunks
        self.method = method
        self.bm25 = BM25Okapi([_tokens(c.text) for c in chunks])
        self._dense = None
        self._char = None

    @property
    def dense_matrix(self) -> np.ndarray:
        if self._dense is None:
            self._dense = dense_embed([c.text for c in self.chunks])
        return self._dense

    @property
    def char_matrix(self) -> np.ndarray:
        if self._char is None:
            self._char = np.vstack([char_embed(c.text) for c in self.chunks])
        return self._char

    def _ranking(self, query: str) -> np.ndarray:
        if self.method == "bm25":
            return np.argsort(-self.bm25.get_scores(_tokens(query)))
        if self.method == "dense":
            q = dense_embed([query])[0]
            return np.argsort(-(self.dense_matrix @ q))
        if self.method == "charngram":
            return np.argsort(-(self.char_matrix @ char_embed(query)))
        # hybrid: reciprocal-rank fusion over bm25 and dense
        bm = np.argsort(-self.bm25.get_scores(_tokens(query)))
        q = dense_embed([query])[0]
        de = np.argsort(-(self.dense_matrix @ q))
        rrf = np.zeros(len(self.chunks))
        for rank, idx in enumerate(bm[:POOL]):
            rrf[idx] += 1.0 / (RRF_K + rank + 1)
        for rank, idx in enumerate(de[:POOL]):
            rrf[idx] += 1.0 / (RRF_K + rank + 1)
        return np.argsort(-rrf)

    def search(self, query: str, k: int = 5) -> list[dict]:
        """Top-k distinct sections, best first."""
        order = self._ranking(query)
        seen: list[str] = []
        out = []
        for rank, idx in enumerate(order[:POOL]):
            c = self.chunks[idx]
            if c.section_id in seen:
                continue
            seen.append(c.section_id)
            out.append({"id": c.section_id, "chunk_id": c.id, "heading": c.heading, "doc": c.doc,
                        "text": c.text, "rank": len(seen)})
            if len(out) == k:
                break
        return out


def recall_at_k(method_index: HybridIndex, questions: list[dict], k: int = 5) -> dict:
    return evaluate(method_index, questions, k)


def evaluate(index: HybridIndex, questions: list[dict], k: int = 5) -> dict:
    """Section-level recall@k, MRR@10 and nDCG@10 for a labelled question set.

    Each question has a single gold section ('chunk' key). Relevance is binary.
    """
    recall, rr, ndcg = [], [], []
    misses = []
    for q in questions:
        hits = index.search(q["q"], 10)
        ids = [h["id"] for h in hits]
        gold = q["chunk"]
        pos = ids.index(gold) + 1 if gold in ids else None
        recall.append(1.0 if pos is not None and pos <= k else 0.0)
        rr.append(1.0 / pos if pos is not None else 0.0)
        ndcg.append(1.0 / math.log2(pos + 1) if pos is not None else 0.0)
        if pos is None or pos > k:
            misses.append({"q": q["q"], "expected": gold, "got": ids[:k]})
    n = len(questions)
    return {"n": n, f"recall@{k}": sum(recall) / n, "mrr@10": sum(rr) / n, "ndcg@10": sum(ndcg) / n,
            "misses": misses}
