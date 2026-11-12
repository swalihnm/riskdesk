"""Retrieval ablation: 2 chunking strategies x 4 scoring methods, on two question sets.

Headline set: evals/rag_eval_v2.jsonl (paraphrased). Reference set: evals/rag_questions.jsonl (v1, written
close to the headings, so it overstates performance; kept only to show the difference).

Usage: python evals/rag_eval.py
Writes evals/results/rag_ablation.json and prints a table.
"""

from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from riskdesk.config import KB_DIR, RAG_QUESTIONS_PATH, RAG_RESULTS_PATH, RAG_V2_PATH  # noqa: E402
from riskdesk.rag.index import HybridIndex, chunk_section, chunk_window, evaluate  # noqa: E402


def load(path: str) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def main() -> None:
    v2 = load(RAG_V2_PATH)
    v1 = load(RAG_QUESTIONS_PATH)
    chunkers = {"section": chunk_section(KB_DIR), "window_60w_overlap20": chunk_window(KB_DIR, 60, 20)}
    results = {}
    print(f"{'chunking':<22}{'method':<11}{'set':<4}{'recall@5':>9}{'MRR@10':>8}{'nDCG@10':>9}{'sec':>7}")
    for cname, chunks in chunkers.items():
        for method in HybridIndex.METHODS:
            t0 = time.time()
            idx = HybridIndex(chunks, method=method)
            for setname, qs in (("v2", v2), ("v1", v1)):
                r = evaluate(idx, qs, k=5)
                results.setdefault(cname, {}).setdefault(method, {})[setname] = {
                    k: v for k, v in r.items() if k != "misses"}
                if setname == "v2":
                    results[cname][method]["v2_misses"] = r["misses"]
                print(f"{cname:<22}{method:<11}{setname:<4}{r['recall@5']:>9.3f}{r['mrr@10']:>8.3f}"
                      f"{r['ndcg@10']:>9.3f}{time.time() - t0:>7.1f}")
    os.makedirs(os.path.dirname(RAG_RESULTS_PATH), exist_ok=True)
    with open(RAG_RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump({"n_v2": len(v2), "n_v1": len(v1), "results": results}, f, indent=2)
    print(f"saved {RAG_RESULTS_PATH}")


if __name__ == "__main__":
    main()
