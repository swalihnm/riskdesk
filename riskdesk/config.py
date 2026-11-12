"""Paths and shared settings. Everything is relative to the repository root."""

from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
CACHE_PATH = os.path.join(DATA_DIR, "cache", "history.parquet")
LIMITS_PATH = os.path.join(DATA_DIR, "limits.json")
KB_DIR = os.path.join(DATA_DIR, "kb")
PROMPTS_DIR = os.path.join(ROOT, "prompts")
TRACE_PATH = os.path.join(DATA_DIR, "traces", "traces.jsonl")
APPROVAL_PATH = os.path.join(DATA_DIR, "approvals.json")
REVIEWERS_PATH = os.path.join(DATA_DIR, "reviewers.json")
GOLDEN_PATH = os.path.join(ROOT, "evals", "golden_set.jsonl")
RAG_QUESTIONS_PATH = os.path.join(ROOT, "evals", "rag_questions.jsonl")  # v1: written close to headings
RAG_V2_PATH = os.path.join(ROOT, "evals", "rag_eval_v2.jsonl")  # v2: paraphrased, the headline set
RAG_RESULTS_PATH = os.path.join(ROOT, "evals", "results", "rag_ablation.json")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("RISKDESK_OLLAMA_MODEL", "qwen2.5:0.5b")
