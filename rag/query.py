#!/usr/bin/env python3
"""Query the local CEIBO RAG index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from langchain_community.vectorstores import Chroma, FAISS
from langchain_huggingface import HuggingFaceEmbeddings


def resolve_index_dir(raw_index_dir: str) -> Path:
    """Resolve index dir from multiple common working directories.

    Supports running from either repo root or from ./rag.
    """
    candidate = Path(raw_index_dir).expanduser()
    if candidate.is_absolute() and candidate.exists():
        return candidate.resolve()

    script_dir = Path(__file__).resolve().parent
    cwd = Path.cwd()
    candidates = [
        cwd / candidate,
        script_dir / candidate,
        script_dir / "index",
        script_dir / "rag" / "index",
        script_dir.parent / "rag" / "index",
        script_dir.parent / "index",
    ]

    for path in candidates:
        if path.exists():
            return path.resolve()

    # Fall back to the first candidate to keep error paths predictable.
    return (cwd / candidate).resolve()


def choose_backend(meta_backend: str, override_backend: Optional[str]) -> str:
    if override_backend:
        return override_backend
    return meta_backend if meta_backend in {"chroma", "faiss"} else "chroma"


def main() -> None:
    parser = argparse.ArgumentParser(description="Query CEIBO local RAG index")
    parser.add_argument("--question", required=True, help="User question")
    parser.add_argument("--index-dir", default="./rag/index", help="Index root directory")
    parser.add_argument("--backend", choices=["chroma", "faiss"], help="Force backend (otherwise read from index metadata)")
    parser.add_argument("--top-k", type=int, default=4)
    args = parser.parse_args()

    index_dir = resolve_index_dir(args.index_dir)
    meta_path = index_dir / "index_meta.json"
    if not meta_path.exists():
        raise SystemExit(
            "Missing index metadata: "
            f"{meta_path}. "
            "Hint: run build_index.py first or pass --index-dir explicitly."
        )

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    backend = choose_backend(str(meta.get("backend", "chroma")), args.backend)
    embeddings_model = meta.get("embeddings_model", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    embeddings = HuggingFaceEmbeddings(model_name=embeddings_model)

    if backend == "chroma":
        db_path = index_dir / "chroma"
        if not db_path.exists():
            raise SystemExit(f"Chroma index not found at: {db_path}")
        vectorstore = Chroma(persist_directory=str(db_path), embedding_function=embeddings)
    else:
        db_path = index_dir / "faiss"
        if not db_path.exists():
            raise SystemExit(f"FAISS index not found at: {db_path}")
        vectorstore = FAISS.load_local(str(db_path), embeddings, allow_dangerous_deserialization=True)

    docs = vectorstore.similarity_search(args.question, k=max(1, args.top_k))

    print(f"Question: {args.question}")
    print(f"Index: {index_dir}")
    print(f"Backend: {backend}\n")
    for i, doc in enumerate(docs, start=1):
        source = doc.metadata.get("source", "unknown")
        snippet = " ".join(doc.page_content.split())[:500]
        print(f"[{i}] source={source}")
        print(f"{snippet}\n")


if __name__ == "__main__":
    main()
