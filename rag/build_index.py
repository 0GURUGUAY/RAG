#!/usr/bin/env python3
"""Build a local RAG index for CEIBO documents.

Usage examples:
  python3 rag/build_index.py --docs-dir ./rag/documents --backend chroma
    
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import BSHTMLLoader, Docx2txtLoader, PyPDFLoader, TextLoader
from langchain_community.vectorstores import Chroma, FAISS
from langchain_huggingface import HuggingFaceEmbeddings

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".docx", ".html", ".htm"}


def iter_source_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path


def load_path(path: Path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        loader = PyPDFLoader(str(path))
    elif suffix in {".txt", ".md"}:
        loader = TextLoader(str(path), encoding="utf-8", autodetect_encoding=True)
    elif suffix == ".docx":
        loader = Docx2txtLoader(str(path))
    elif suffix in {".html", ".htm"}:
        loader = BSHTMLLoader(str(path))
    else:
        raise ValueError(f"Unsupported file type for {path}")
    docs = loader.load()
    for doc in docs:
        doc.metadata = doc.metadata or {}
        doc.metadata["source"] = str(path)
    return docs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build CEIBO local RAG index")
    parser.add_argument("--docs-dir", required=True, help="Directory containing source docs")
    parser.add_argument("--backend", choices=["chroma", "faiss"], default="chroma")
    parser.add_argument("--out-dir", default="./rag/index", help="Directory to persist index")
    parser.add_argument(
        "--embeddings-model",
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        help="Embedding model name",
    )
    parser.add_argument("--chunk-size", type=int, default=1500)
    parser.add_argument("--chunk-overlap", type=int, default=200)
    args = parser.parse_args()

    docs_dir = Path(args.docs_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    files = list(iter_source_files(docs_dir))
    if not files:
        raise SystemExit(f"No supported files found in {docs_dir}")

    raw_docs = []
    failed_files = []
    for path in files:
        try:
            raw_docs.extend(load_path(path))
        except Exception as exc:
            failed_files.append({"path": str(path), "error": str(exc)})
            print(f"[WARN] Ignored file: {path} ({exc})")

    if not raw_docs:
        raise SystemExit(
            f"No readable documents found in {docs_dir}. Failed files: {len(failed_files)}"
        )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max(300, args.chunk_size),
        chunk_overlap=max(0, min(args.chunk_overlap, args.chunk_size // 2)),
    )
    chunks = splitter.split_documents(raw_docs)

    embeddings = HuggingFaceEmbeddings(model_name=args.embeddings_model)

    if args.backend == "chroma":
        db_dir = out_dir / "chroma"
        db_dir.mkdir(parents=True, exist_ok=True)
        db = Chroma.from_documents(chunks, embedding=embeddings, persist_directory=str(db_dir))
        db.persist()
        backend_path = str(db_dir)
    else:
        db = FAISS.from_documents(chunks, embedding=embeddings)
        db_dir = out_dir / "faiss"
        db_dir.mkdir(parents=True, exist_ok=True)
        db.save_local(str(db_dir))
        backend_path = str(db_dir)

    meta = {
        "backend": args.backend,
        "backend_path": backend_path,
        "embeddings_model": args.embeddings_model,
        "files_indexed": len(files),
        "chunks_indexed": len(chunks),
        "files_failed": len(failed_files),
    }
    meta_path = out_dir / "index_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    if failed_files:
        failures_path = out_dir / "index_failures.json"
        failures_path.write_text(json.dumps(failed_files, indent=2), encoding="utf-8")

    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
