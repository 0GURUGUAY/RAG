# CEIBO RAG local

## Objectif
Indexer localement la documentation du bateau pour retrouver rapidement des informations techniques via recherche sémantique.

Le flux RAG est configure pour les requetes en francais, espagnol et anglais.

## Stack
- LangChain
- Embeddings: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- Vector store: ChromaDB (par défaut) ou FAISS

## Installation
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r rag/requirements.txt
```

## Préparer les documents
Placer les documents dans `rag/documents/` (PDF, TXT, MD, DOCX, HTML).

Le script utilise des loaders natifs LangChain (`PyPDFLoader`, `TextLoader`, `Docx2txtLoader`, `BSHTMLLoader`) pour rester léger et compatible en local.

## Construire l'index
```bash
python3 rag/build_index.py --docs-dir ./rag/documents --backend chroma
```

## Interroger l'index
```bash
python3 rag/query.py --question "Quel est le protocole de purge du circuit gasoil ?"
```

## Chat RAG dans l'application CEIBO
L'application web peut interroger le RAG via une API locale HTTP.

1) Installer les dépendances (inclut FastAPI/Uvicorn):
```bash
pip install -r rag/requirements.txt
```

2) Lancer le serveur local RAG:
```bash
python3 rag/server.py --host 127.0.0.1 --port 8765
```

3) Ouvrir l'onglet `Document` dans CEIBO, poser la question dans la zone RAG puis cliquer `Poser la question`.

L'application transmet automatiquement la langue active (`fr`, `es` ou `en`) au serveur RAG.

Si le serveur n'est pas lancé, l'application affichera un message d'erreur avec la commande de démarrage.

### Mode externe (LLM) et Gemini

Dans `Document > IA`, le mode `Externe` (ou `Hybride`) permet d'utiliser un fournisseur distant.

- Providers supportes: `openai`, `openrouter`, `mistral`, `gemini`
- Pour Gemini, vous pouvez renseigner la cle API dans l'UI ou utiliser une variable d'environnement:
	- `GEMINI_API_KEY` (recommande)
	- `GOOGLE_API_KEY` (fallback accepte)
- Modele Gemini par defaut: `gemini-1.5-flash`

## Variante FAISS
```bash
python3 rag/build_index.py --docs-dir ./rag/documents --backend faiss
python3 rag/query.py --question "Quelle pression d'huile nominale ?"
```
