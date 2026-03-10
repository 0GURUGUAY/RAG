#!/usr/bin/env python3
"""Local HTTP bridge for CEIBO RAG queries.

Run:
  python3 rag/server.py --host 127.0.0.1 --port 8765
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_community.vectorstores import Chroma, FAISS
from langchain_huggingface import HuggingFaceEmbeddings
import uvicorn

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

STOPWORDS = {
    "a",
    "au",
    "aux",
    "avec",
    "ce",
    "ces",
    "dans",
    "de",
    "des",
    "du",
    "en",
    "et",
    "est",
    "la",
    "le",
    "les",
    "mais",
    "ou",
    "par",
    "pour",
    "que",
    "qui",
    "se",
    "sur",
    "un",
    "une",
    "from",
    "for",
    "with",
    "the",
    "is",
    "are",
    "el",
    "los",
    "las",
    "por",
    "para",
    "con",
    "del",
    "una",
    "que",
    "bateau",
    "boat",
    "ship",
    "vessel",
    "quel",
    "quelle",
    "quels",
    "quelles",
    "what",
    "which",
    "cual",
    "cuales",
}

IDENTITY_TERMS = {
    "callsign",
    "call",
    "sign",
    "mmsi",
    "indicatif",
    "distinctive",
    "official",
    "number",
}

INSURANCE_TERMS = {
    "assurance",
    "assure",
    "assureur",
    "insured",
    "insurance",
    "policy",
    "police",
    "attestation",
    "certificate",
    "certificat",
    "generali",
    "date",
    "effet",
    "debut",
    "validite",
    "garantie",
    "sinistre",
}

ENGINE_TERMS = {
    "moteur",
    "engine",
    "volvo",
    "penta",
    "temperature",
    "oil",
    "rpm",
    "alternateur",
    "coolant",
}

DATE_TERMS = {
    "date",
    "effet",
    "debut",
    "from",
    "since",
    "inception",
    "starting",
    "commence",
    "commencement",
    "validite",
}

MANUFACTURE_TERMS = {
    "fabrication",
    "construction",
    "construit",
    "built",
    "build",
    "model",
    "modele",
    "annee",
    "year",
}

MANUFACTURE_CONTEXT_TERMS = {
    "annee",
    "fabrication",
    "construction",
    "caracteristiques",
    "detail",
    "modele",
    "constructeur",
    "bateau",
    "boat",
    "navire",
    "vessel",
}

MANUFACTURE_SOURCE_HINTS = {
    "conditions particulieres",
    "yacht sale agreement",
    "addendum",
    "ceibo",
    "inventaire",
}

MANUAL_SOURCE_HINTS = {
    "guide",
    "notice",
    "installation",
    "volvo",
    "ray50",
    "ray52",
    "ray60",
    "ray70",
}

STRUCTURED_FIELD_SOURCE_HINTS = {
    "conditions particulieres",
    "yacht sale agreement",
    "addendum",
    "ceibo",
}

STRUCTURED_FIELD_LABEL_MAP = {
    "type de coque": "hull_type",
    "marque/ constructeur": "builder",
    "marque constructeur": "builder",
    "modele": "model",
    "materiaux": "materials",
    "longueur": "length",
    "valeur": "value",
    "pavillon": "flag",
    "port d'attache": "home_port",
    "port d attache": "home_port",
    "zone de navigation": "navigation_zone",
}

STRUCTURED_FIELD_SPECS = {
    "hull_type": {
        "intent_terms": {"type", "coque", "hull"},
        "label": {"fr": "type de coque", "es": "tipo de casco", "en": "hull type"},
    },
    "builder": {
        "intent_terms": {"marque", "constructeur", "builder", "shipyard", "chantier"},
        "label": {"fr": "marque / constructeur", "es": "marca / astillero", "en": "builder"},
    },
    "model": {
        "intent_terms": {"modele", "model"},
        "label": {"fr": "modele", "es": "modelo", "en": "model"},
    },
    "materials": {
        "intent_terms": {"materiau", "materiaux", "material", "materials", "composite", "polyester"},
        "label": {"fr": "materiaux", "es": "materiales", "en": "materials"},
    },
    "length": {
        "intent_terms": {"longueur", "length", "meters", "metres", "metres", "taille"},
        "label": {"fr": "longueur", "es": "longitud", "en": "length"},
    },
    "value": {
        "intent_terms": {"valeur", "prix", "value", "price", "eur", "euro"},
        "label": {"fr": "valeur", "es": "valor", "en": "value"},
    },
    "flag": {
        "intent_terms": {"pavillon", "flag", "bandera", "immatriculation"},
        "label": {"fr": "pavillon", "es": "pabellon", "en": "flag"},
    },
    "home_port": {
        "intent_terms": {"port", "attache", "homeport", "amarre", "base"},
        "label": {"fr": "port d'attache", "es": "puerto base", "en": "home port"},
    },
    "navigation_zone": {
        "intent_terms": {"zone", "navigation", "area", "cruising"},
        "label": {"fr": "zone de navigation", "es": "zona de navegacion", "en": "navigation zone"},
    },
}

EMERGENCY_TERMS = {
    "urgence",
    "urgences",
    "detresse",
    "distress",
    "mayday",
    "pan",
    "secours",
    "rescue",
    "maritime",
    "vhf",
    "canal",
    "channel",
}

FREQUENCY_TERMS = {
    "frequence",
    "frequency",
    "mhz",
    "khz",
    "canal",
    "channel",
    "ch",
    "16",
    "156",
    "1568",
}

MARITIME_TERMS = {
    "bateau",
    "boat",
    "navire",
    "vessel",
    "maritime",
    "mer",
    "sea",
    "vhf",
    "canal",
    "channel",
    "port",
    "ancre",
    "anchor",
    "mouillage",
    "route",
    "navigation",
    "skipper",
    "equipage",
}

EQUIPMENT_TERMS = {
    "equipement",
    "equipements",
    "equipment",
    "equipamiento",
    "inventory",
    "liste",
    "list",
}

BOAT_CONTEXT_TERMS = {
    "bateau",
    "boat",
    "ship",
    "vessel",
    "navire",
}

BOAT_IDENTITY_TERMS = {
    "ceibo",
    "dufour",
    "exclusive",
    "56",
}

SPEED_TERMS = {
    "vitesse",
    "speed",
    "maximale",
    "maximum",
    "max",
    "top",
    "kn",
    "kts",
    "kt",
    "knot",
    "knots",
    "noeud",
    "noeuds",
    "nds",
    "nd",
}

DISTANCE_TERMS = {
    "distance",
    "distancia",
    "nm",
    "nmi",
    "mille",
    "milles",
    "mile",
    "miles",
    "km",
}

NAV_GUIDANCE_TERMS = {
    "navigation",
    "naviguation",
    "navigacion",
    "navigating",
    "route",
    "itineraire",
    "cap",
    "voilier",
    "sailing",
    "sailboat",
    "bateau",
    "boat",
    "entre",
    "between",
}

REFUSAL_CONTEXT_PATTERNS = (
    "contexte documentaire fourni ne contient pas",
    "le contexte documentaire fourni",
    "contexte documentaire fourni",
    "context provided does not contain",
    "the provided context",
    "provided context does not contain",
    "el contexto proporcionado no contiene",
)

CARTOGRAPHY_TERMS = {
    "lecteur",
    "carte",
    "cartographie",
    "plotter",
    "gps",
    "ecran",
    "multifonctions",
    "navigation",
    "raymarine",
}

RADIO_TERMS = {
    "vhf",
    "radio",
    "asn",
    "ais",
    "canal",
    "channel",
}

CHARTPLOTTER_BRANDS = {
    "raymarine",
    "garmin",
    "simrad",
    "furuno",
    "b&g",
}

EQUIPMENT_SOURCE_HINTS = {
    "yacht sale agreement",
    "addendum",
    "inventaire",
    "inventory",
    "equipement",
    "equipements",
}

DATE_PATTERNS = [
    re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"),
    re.compile(r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b"),
    re.compile(
        r"\b\d{1,2}\s+(?:janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)\s+\d{4}\b",
        re.IGNORECASE,
    ),
]

EMERGENCY_FREQUENCY_PATTERNS = [
    re.compile(r"\b156[\.,]8\s*mhz\b", re.IGNORECASE),
    re.compile(r"\b156[\.,]8\b", re.IGNORECASE),
    re.compile(r"\b(?:canal|channel|ch)\s*16\b", re.IGNORECASE),
]


class QueryPayload(BaseModel):
    question: str
    top_k: int = 4
    index_dir: Optional[str] = None
    backend: Optional[str] = None
    language: Optional[str] = None


class BuildPayload(BaseModel):
    docs_dir: Optional[str] = None
    backend: str = "faiss"
    out_dir: Optional[str] = None
    embeddings_model: Optional[str] = None
    chunk_size: int = 1000
    chunk_overlap: int = 150


class DebugQueryPayload(QueryPayload):
    candidate_k: Optional[int] = None


class LlmQueryPayload(QueryPayload):
    mode: str = "hybrid"  # local | external | hybrid
    provider: str = "gemini"
    response_style: str = "concise"  # concise | detailed
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 900


BUILD_INDEX_LOCK = threading.Lock()


def detect_language(raw_language: Optional[str], text: str) -> str:
    value = str(raw_language or "").strip().lower()
    if value in {"fr", "es", "en"}:
        return value

    lowered = str(text or "").lower()
    if any(token in lowered for token in (" que ", " para ", " barco", " fondeo", " mantenimiento", " aceite")):
        return "es"
    if any(token in lowered for token in (" what ", " where ", " engine", "boat", "anchorage", "maintenance", "oil")):
        return "en"
    return "fr"


def localized_no_result(language: str) -> str:
    if language == "es":
        return "No se encontro ningun extracto relevante."
    if language == "en":
        return "No relevant excerpt was found."
    return "Aucun extrait pertinent trouve."


def resolve_index_dir(raw_index_dir: Optional[str]) -> Path:
    script_dir = Path(__file__).resolve().parent
    cwd = Path.cwd()
    if raw_index_dir:
        candidate = Path(raw_index_dir).expanduser()
        if candidate.is_absolute() and candidate.exists():
            return candidate.resolve()
        candidates = [
            cwd / candidate,
            script_dir / candidate,
            script_dir.parent / candidate,
        ]
    else:
        # Prioritize the canonical index near this server module.
        candidates = [
            script_dir / "index",
            script_dir.parent / "rag" / "index",
            cwd / "rag" / "index",
            cwd / "index",
        ]

    for path in candidates:
        if path.exists():
            return path.resolve()

    if raw_index_dir:
        return (cwd / Path(raw_index_dir).expanduser()).resolve()
    return (script_dir / "index").resolve()


def load_vectorstore(index_dir: Path, backend_override: Optional[str] = None):
    meta_path = index_dir / "index_meta.json"
    if not meta_path.exists():
        raise RuntimeError(f"Missing index metadata: {meta_path}")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    backend = backend_override or str(meta.get("backend", "chroma"))
    if backend not in {"chroma", "faiss"}:
        backend = "chroma"

    embeddings_model = str(meta.get("embeddings_model", DEFAULT_MODEL))
    embeddings = HuggingFaceEmbeddings(model_name=embeddings_model)

    if backend == "chroma":
        db_path = index_dir / "chroma"
        if not db_path.exists():
            raise RuntimeError(f"Chroma index not found at: {db_path}")
        vectorstore = Chroma(persist_directory=str(db_path), embedding_function=embeddings)
    else:
        db_path = index_dir / "faiss"
        if not db_path.exists():
            raise RuntimeError(f"FAISS index not found at: {db_path}")
        vectorstore = FAISS.load_local(str(db_path), embeddings, allow_dangerous_deserialization=True)

    return {
        "vectorstore": vectorstore,
        "backend": backend,
        "embeddings_model": embeddings_model,
    }


def format_docs(docs: List[Any]) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    for idx, doc in enumerate(docs):
        source = str(doc.metadata.get("source", "unknown"))
        snippet_full = " ".join(str(doc.page_content or "").split())
        # Keep the first result fully visible in the UI, while keeping other
        # snippets compact to avoid an overloaded source panel.
        snippet = snippet_full if idx == 0 else snippet_full[:500]
        results.append({"source": source, "snippet": snippet})
    return results


def _normalize_text(value: str) -> str:
    lowered = str(value or "").lower()
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(ch)
    )


def _tokenize(value: str) -> List[str]:
    normalized = _normalize_text(value)
    tokens = re.findall(r"[a-z0-9]{2,}", normalized)
    return [tok for tok in tokens if tok not in STOPWORDS]


def _find_dates(value: str) -> List[str]:
    text = _normalize_text(value)
    found: List[str] = []
    for pattern in DATE_PATTERNS:
        for match in pattern.findall(text):
            if isinstance(match, tuple):
                continue
            if match not in found:
                found.append(match)
    return found


def _extract_structured_values_from_text(value: str) -> Dict[str, str]:
    normalized = _normalize_text(value)
    if not normalized:
        return {}

    matches: List[Tuple[int, int, str]] = []
    for label, field_key in STRUCTURED_FIELD_LABEL_MAP.items():
        for match in re.finditer(rf"\b{re.escape(label)}\s*:", normalized):
            matches.append((match.start(), match.end(), field_key))

    if not matches:
        return {}

    matches.sort(key=lambda item: item[0])
    extracted: Dict[str, str] = {}
    for idx, (_, end, field_key) in enumerate(matches):
        next_start = matches[idx + 1][0] if idx + 1 < len(matches) else len(normalized)
        raw_candidate = normalized[end:next_start].strip(" :-;,.\n\r\t")
        candidate = _clean_equipment_value(raw_candidate)
        if not candidate:
            continue
        if field_key == "value":
            amount_match = re.search(r"\b\d[\d\s.,]{2,}\s*(?:eur|euro|usd|€)?\b", candidate)
            if not amount_match:
                continue
            candidate = _clean_equipment_value(amount_match.group(0))
        if field_key == "length":
            length_match = re.search(r"\b\d[\d\s.,]*\s*(?:m|metre|metres|meter|meters)\b", candidate)
            if not length_match:
                continue
            candidate = _clean_equipment_value(length_match.group(0))
        extracted[field_key] = candidate

    return extracted


def _detect_structured_field_intent(question: str) -> Optional[str]:
    question_tokens = set(_tokenize(question))
    best_field: Optional[str] = None
    best_score = 0

    for field_key, spec in STRUCTURED_FIELD_SPECS.items():
        intent_terms = set(spec.get("intent_terms", set()))
        score = len(question_tokens & intent_terms)
        if score > best_score:
            best_score = score
            best_field = field_key

    return best_field if best_score > 0 else None


def _is_equipment_question(question: str) -> bool:
    tokens = set(_tokenize(question))
    return bool(tokens & EQUIPMENT_TERMS) or bool(tokens & CARTOGRAPHY_TERMS)


def _is_speed_intent(question: str) -> bool:
    tokens = set(_tokenize(question))
    return bool(tokens & SPEED_TERMS)


def _is_boat_speed_question(question: str) -> bool:
    tokens = set(_tokenize(question))
    return _is_speed_intent(question) and (
        bool(tokens & BOAT_CONTEXT_TERMS) or bool(tokens & BOAT_IDENTITY_TERMS)
    )


def _is_distance_navigation_question(question: str) -> bool:
    tokens = set(_tokenize(question))
    has_distance = bool(tokens & DISTANCE_TERMS)
    has_navigation = bool(tokens & NAV_GUIDANCE_TERMS)
    return has_distance and has_navigation


def _looks_like_off_topic_equipment_answer(question: str, text: Optional[str]) -> bool:
    if not _is_distance_navigation_question(question):
        return False

    answer_tokens = set(_tokenize(str(text or "")))
    if not answer_tokens:
        return False

    equipment_hits = len(EQUIPMENT_TERMS & answer_tokens) + len(RADIO_TERMS & answer_tokens)
    distance_hits = len(DISTANCE_TERMS & answer_tokens)
    return equipment_hits > 0 and distance_hits == 0


def _build_retrieval_question(question: str) -> str:
    expanded = question
    if _is_manufacture_year_intent(question):
        return f"{question} annee construction detail bateau caracteristiques"

    if _is_boat_speed_question(question):
        return (
            f"{question} performance vitesse maximale bateau dufour ceibo "
            "caracteristiques detail conditions particulieres addendum"
        ).strip()

    structured_field = _detect_structured_field_intent(question)
    if structured_field:
        field_spec = STRUCTURED_FIELD_SPECS.get(structured_field, {})
        field_terms = " ".join(sorted(field_spec.get("intent_terms", [])))
        expanded = f"{question} caracteristiques bateau detail {field_terms}".strip()
    return expanded


def _extract_speed_answer(question: str, docs: List[Any], language: str) -> Optional[str]:
    if not _is_boat_speed_question(question):
        return None

    question_tokens = set(_tokenize(question))
    target_identity = BOAT_IDENTITY_TERMS & question_tokens

    candidates: List[Tuple[float, str]] = []
    patterns = [
        re.compile(r"\b(\d{1,2}(?:[.,]\d)?)\s*(?:kts?|kt|knots?|nds?|nd|noeuds?)\b"),
        re.compile(r"\b(?:vitesse\s*(?:maximale|maximum|max)?|top\s*speed|max\s*speed)\D{0,24}(\d{1,2}(?:[.,]\d)?)\b"),
    ]

    for doc_rank, doc in enumerate(docs):
        source = str(doc.metadata.get("source", ""))
        source_norm = _normalize_text(source)
        text = str(doc.page_content or "")
        text_norm = _normalize_text(text)

        doc_tokens = set(_tokenize(f"{source} {text}"))
        identity_hits = len(target_identity & doc_tokens) if target_identity else len(BOAT_IDENTITY_TERMS & doc_tokens)
        speed_hits = len(SPEED_TERMS & doc_tokens)

        source_bonus = 0.0
        if any(hint in source_norm for hint in STRUCTURED_FIELD_SOURCE_HINTS):
            source_bonus += 0.30
        if any(hint in source_norm for hint in MANUAL_SOURCE_HINTS):
            source_bonus -= 0.12

        base_rank = max(0.0, 1.4 - (doc_rank * 0.2))
        context_score = base_rank + (identity_hits * 0.10) + min(0.25, speed_hits * 0.05) + source_bonus

        for pattern in patterns:
            for match in pattern.finditer(text_norm):
                value = match.group(1).replace(",", ".").strip()
                if not value:
                    continue
                try:
                    numeric = float(value)
                except Exception:
                    continue
                if numeric <= 0 or numeric > 60:
                    continue
                candidates.append((context_score, f"{value} nds"))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    best_value = candidates[0][1]
    if language == "es":
        return f"Velocidad maxima detectada en la documentacion: {best_value}."
    if language == "en":
        return f"Maximum speed detected in documentation: {best_value}."
    return f"Vitesse maximale detectee dans la documentation: {best_value}."


def _looks_like_context_refusal(text: Optional[str]) -> bool:
    normalized = _normalize_text(str(text or ""))
    return any(pattern in normalized for pattern in REFUSAL_CONTEXT_PATTERNS)


def _general_fallback_answer(question: str, language: str) -> str:
    if _is_boat_speed_question(question):
        if language == "es":
            return (
                "Segun conocimientos generales, un Dufour 56 suele navegar alrededor de 8 a 10 nds "
                "en crucero y puede superar ese valor en buenas condiciones. "
                "No he podido extraer aqui una cifra certificada unica desde el contexto recuperado."
            )
        if language == "en":
            return (
                "Based on general knowledge, a Dufour 56 typically cruises around 8 to 10 knots "
                "and can exceed that in favorable conditions. "
                "I could not reliably extract a single certified maximum value from the retrieved context."
            )
        return (
            "Selon mes connaissances generales, un Dufour 56 navigue souvent autour de 8 a 10 nds "
            "en croisiere et peut depasser cette valeur dans de bonnes conditions. "
            "Je n'ai pas pu extraire ici une valeur maximale certifiee unique depuis le contexte recupere."
        )

    if _is_distance_navigation_question(question):
        q_norm = _normalize_text(question)
        is_antibes_sttropez = ("antibes" in q_norm) and ("saint tropez" in q_norm or "st tropez" in q_norm)

        if is_antibes_sttropez:
            if language == "es":
                return (
                    "Segun conocimientos generales, la distancia Antibes - Saint-Tropez es de aproximadamente 34 a 38 NM "
                    "(segun salida/llegada exactas). Para un velero de 56 pies: vigila el Mistral, prioriza una derrota costera "
                    "prudente, verifica trafico y zonas reguladas, y planifica alternativas de abrigo (p. ej. Cannes / Frejus / golfo de Saint-Tropez)."
                )
            if language == "en":
                return (
                    "Based on general knowledge, Antibes to Saint-Tropez is roughly 34 to 38 NM "
                    "(depending on exact departure/arrival points). For a 56-foot sailboat: monitor Mistral conditions, "
                    "keep a prudent coastal route, check traffic and regulated areas, and prepare shelter alternatives "
                    "(e.g. Cannes / Frejus / Gulf of Saint-Tropez)."
                )
            return (
                "Selon mes connaissances generales, la distance Antibes - Saint-Tropez est d'environ 34 a 38 NM "
                "(selon les points de depart/arrivee exacts). Pour un voilier de 56 pieds: surveille le Mistral, "
                "privilegie une route cotiere prudente, controle trafic et zones reglementees, "
                "et prepare des abris de repli (ex: Cannes / Frejus / golfe de Saint-Tropez)."
            )

    return localized_no_result(language)


def _extract_structured_field_answer(question: str, docs: List[Any], language: str) -> Optional[str]:
    field_key = _detect_structured_field_intent(question)
    if not field_key:
        return None

    best_value: Optional[str] = None
    best_score = -999

    for doc_rank, doc in enumerate(docs):
        source_norm = _normalize_text(str(doc.metadata.get("source", "")))
        values = _extract_structured_values_from_text(str(doc.page_content or ""))
        candidate = values.get(field_key)
        if not candidate:
            continue

        score = 3 - min(3, doc_rank)
        if any(hint in source_norm for hint in STRUCTURED_FIELD_SOURCE_HINTS):
            score += 3
        if any(hint in source_norm for hint in MANUAL_SOURCE_HINTS):
            score -= 2

        if score > best_score:
            best_score = score
            best_value = candidate

    if not best_value:
        return None

    labels = STRUCTURED_FIELD_SPECS[field_key]["label"]
    label = labels.get(language, labels.get("fr", field_key))
    if language == "es":
        return f"Valor encontrado para '{label}': {best_value}."
    if language == "en":
        return f"Value found for '{label}': {best_value}."
    return f"Valeur trouvee pour '{label}': {best_value}."


def _resolve_llm_provider_settings(provider: str) -> Tuple[str, str, str]:
    key = str(provider or "gemini").strip().lower()
    if key == "gemini":
        return (
            "https://generativelanguage.googleapis.com/v1beta",
            "GEMINI_API_KEY",
            "gemini-2.5-flash",
        )
    if key == "mistral":
        return (
            "https://api.mistral.ai/v1",
            "MISTRAL_API_KEY",
            "mistral-small-latest",
        )
    if key == "openrouter":
        return (
            "https://openrouter.ai/api/v1",
            "OPENROUTER_API_KEY",
            "openai/gpt-4o-mini",
        )
    return (
        "https://api.openai.com/v1",
        "OPENAI_API_KEY",
        "gpt-4o-mini",
    )


def _normalize_gemini_model_path(model: str) -> str:
    value = str(model or "").strip()
    if not value:
        value = "gemini-2.5-flash"
    return value if value.startswith("models/") else f"models/{value}"


def _list_gemini_generate_models(api_base: str, api_key: str) -> List[str]:
    url = f"{api_base}/models?key={urllib.parse.quote(api_key)}"
    req = urllib.request.Request(url=url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    try:
        parsed = json.loads(raw)
    except Exception:
        return []

    models: List[str] = []
    for item in parsed.get("models", []) or []:
        methods = item.get("supportedGenerationMethods") or []
        if "generateContent" not in methods:
            continue
        name = str(item.get("name") or "").strip()
        if name.startswith("models/"):
            models.append(name)
    return models


def _pick_gemini_fallback_model(available_models: List[str], tried_models: List[str]) -> Optional[str]:
    if not available_models:
        return None

    tried = set(tried_models)
    preferred = [
        "models/gemini-2.5-flash",
        "models/gemini-2.5-flash-lite",
        "models/gemini-1.5-flash",
        "models/gemini-1.5-flash-8b",
        "models/gemini-1.5-pro",
    ]
    for candidate in preferred:
        if candidate in available_models and candidate not in tried:
            return candidate
    for candidate in available_models:
        if candidate not in tried:
            return candidate
    return None


def _extract_retry_delay_seconds(raw: str) -> Optional[int]:
    text = str(raw or "")
    direct = re.search(r'"retryDelay"\s*:\s*"(\d+)s"', text)
    if direct:
        try:
            return int(direct.group(1))
        except Exception:
            return None

    inline = re.search(r"Please retry in\s+([0-9]+(?:\.[0-9]+)?)s", text, flags=re.IGNORECASE)
    if inline:
        try:
            return max(1, int(float(inline.group(1))))
        except Exception:
            return None
    return None


def _raise_external_http_error(http_status: int, details: str) -> None:
    details_text = str(details or "")
    details_lc = details_text.lower()
    is_quota = (
        http_status == 429
        or "resource_exhausted" in details_lc
        or "quota exceeded" in details_lc
    )
    if is_quota:
        retry_seconds = _extract_retry_delay_seconds(details_text)
        retry_hint = f" Retry in about {retry_seconds}s." if retry_seconds else ""
        raise HTTPException(
            status_code=429,
            detail=(
                "Gemini quota exceeded (rate limit / billing)."
                " Check Gemini API quotas and billing settings."
                f"{retry_hint}"
            ),
        )

    raise HTTPException(status_code=502, detail=f"External LLM HTTP error: {details_text}")


def _call_external_llm(payload: LlmQueryPayload, language: str, sources: List[Dict[str, str]]) -> str:
    provider_key = str(payload.provider or "gemini").strip().lower()
    default_base, env_key_name, default_model = _resolve_llm_provider_settings(payload.provider)
    api_base = str(payload.api_base or os.getenv("LLM_API_BASE") or default_base).rstrip("/")
    api_key = str(payload.api_key or os.getenv(env_key_name) or "").strip()
    if provider_key == "gemini" and not api_key:
        # Accept Google-style env var as fallback for Gemini.
        api_key = str(os.getenv("GOOGLE_API_KEY") or "").strip()
    model = str(payload.model or os.getenv("LLM_MODEL") or default_model).strip()

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"API key missing. Provide api_key or set {env_key_name}.",
        )

    context_blocks = []
    for idx, item in enumerate(sources[:8], start=1):
        context_blocks.append(
            f"[{idx}] SOURCE: {item.get('source', 'unknown')}\n[{idx}] SNIPPET: {item.get('snippet', '')}"
        )
    context = "\n\n".join(context_blocks)

    lang_instruction = "Reponds en francais." if language == "fr" else "Respond in English." if language == "en" else "Responde en espanol."
    response_style = str(payload.response_style or "concise").strip().lower()
    if response_style not in {"concise", "detailed"}:
        response_style = "concise"

    style_instruction = (
        "Format concis: 3 a 6 lignes claires."
        if response_style == "concise"
        else (
            "Format detaille: reponds en sections courtes avec titres. Inclure: "
            "(1) reponse directe, (2) facteurs/conditions, (3) conseils pratiques de navigation, "
            "(4) limites/incertitudes."
        )
    )

    user_prompt = (
        f"Question: {payload.question}\n\n"
        f"Contexte documentaire (optionnel):\n{context}\n\n"
        "Regles:\n"
        "1) Utilise d'abord le contexte documentaire s'il contient l'information demandee.\n"
        "2) Si le contexte ne suffit pas, reponds avec tes connaissances generales au lieu de refuser.\n"
        "3) Quand tu utilises des connaissances generales, indique-le explicitement en debut de phrase (ex: 'Selon mes connaissances generales...').\n"
        "4) Si la valeur exacte est incertaine, donne une plage ou un ordre de grandeur et signale l'incertitude.\n"
        "5) N'affirme jamais qu'une information est absente uniquement parce qu'elle n'est pas dans le contexte fourni.\n"
        "6) Si le contexte est hors sujet par rapport a la question, ignore-le et reponds directement a la question.\n"
        f"7) {style_instruction}"
    )
    if provider_key == "gemini":
        max_tokens = int(payload.max_tokens or 350)
        if response_style == "detailed":
            max_tokens = max(max_tokens, 700)
        body = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                f"Tu es un assistant nautique precis. {lang_instruction}\n\n{user_prompt}"
                            )
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": float(payload.temperature or 0.2),
                "maxOutputTokens": max_tokens,
            },
        }

        raw = ""
        tried_models: List[str] = []
        pending_models: List[str] = [_normalize_gemini_model_path(model)]
        did_try_catalog_fallback = False
        used_model_path = pending_models[0]

        while pending_models:
            model_path = pending_models.pop(0)
            if model_path in tried_models:
                continue
            tried_models.append(model_path)

            req = urllib.request.Request(
                url=f"{api_base}/{model_path}:generateContent?key={urllib.parse.quote(api_key)}",
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                },
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=28) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                used_model_path = model_path
                break
            except urllib.error.HTTPError as exc:
                details = exc.read().decode("utf-8", errors="replace")
                details_lc = details.lower()
                not_found_model = exc.code == 404 and (
                    ("not_found" in details_lc and "model" in details_lc)
                    or "no longer available" in details_lc
                    or "not found for api version" in details_lc
                    or "not supported for generatecontent" in details_lc
                )
                if not_found_model and not did_try_catalog_fallback:
                    did_try_catalog_fallback = True
                    available_models = _list_gemini_generate_models(api_base, api_key)
                    fallback_model = _pick_gemini_fallback_model(available_models, tried_models)
                    if fallback_model:
                        pending_models.append(fallback_model)
                        continue
                _raise_external_http_error(exc.code, details)
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"External LLM call failed: {exc}") from exc

        if not raw:
            raise HTTPException(status_code=502, detail="External LLM returned an empty answer.")

        parsed = json.loads(raw)
        candidate = (parsed.get("candidates") or [{}])[0] or {}
        parts = candidate.get("content", {}).get("parts", [])
        text = "\n".join(str(part.get("text", "")).strip() for part in parts if part.get("text"))
        finish_reason = str(candidate.get("finishReason") or "").strip().lower()

        # If Gemini stopped due to token cap, request a continuation once.
        if text and finish_reason in {"max_tokens", "length", "token_limit"}:
            continuation_prompt = (
                "Continue EXACTEMENT la reponse precedente la ou elle s'est arretee, "
                "sans repetition, sans nouvelle introduction.\n\n"
                f"Question initiale: {payload.question}\n\n"
                f"Reponse partielle deja envoyee:\n{text}"
            )
            continuation_body = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": f"Tu es un assistant nautique precis. {lang_instruction}\n\n{continuation_prompt}"
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": float(payload.temperature or 0.2),
                    "maxOutputTokens": max(max_tokens, 1200),
                },
            }
            continuation_req = urllib.request.Request(
                url=f"{api_base}/{used_model_path}:generateContent?key={urllib.parse.quote(api_key)}",
                data=json.dumps(continuation_body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(continuation_req, timeout=28) as response:
                    continuation_raw = response.read().decode("utf-8", errors="replace")
                continuation_parsed = json.loads(continuation_raw)
                continuation_candidate = (continuation_parsed.get("candidates") or [{}])[0] or {}
                continuation_parts = continuation_candidate.get("content", {}).get("parts", [])
                continuation_text = "\n".join(
                    str(part.get("text", "")).strip() for part in continuation_parts if part.get("text")
                ).strip()
                if continuation_text:
                    text = f"{text.rstrip()}\n{continuation_text.lstrip()}"
            except Exception:
                # Keep the first segment if continuation fails.
                pass
    else:
        body = {
            "model": model,
            "temperature": float(payload.temperature or 0.2),
            "max_tokens": int(payload.max_tokens or 350),
            "messages": [
                {
                    "role": "system",
                    "content": f"Tu es un assistant nautique precis. {lang_instruction}",
                },
                {"role": "user", "content": user_prompt},
            ],
        }
        req = urllib.request.Request(
            url=f"{api_base}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=28) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            _raise_external_http_error(exc.code, details)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"External LLM call failed: {exc}") from exc

        parsed = json.loads(raw)
        text = (
            parsed.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
    text = str(text or "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="External LLM returned an empty answer.")
    return text


def _is_manufacture_year_intent(question: str) -> bool:
    tokens = set(_tokenize(question))
    has_year = any(tok in tokens for tok in ("annee", "year"))
    has_build = any(tok in tokens for tok in ("fabrication", "construction", "construit", "built", "build"))
    has_boat = any(tok in tokens for tok in BOAT_CONTEXT_TERMS)
    return (has_year and has_boat) or (has_build and (has_boat or has_year))


def _extract_manufacture_year_answer(question: str, docs: List[Any], language: str) -> Optional[str]:
    if not _is_manufacture_year_intent(question):
        return None

    best_year: Optional[str] = None
    best_score = -999

    for doc_rank, doc in enumerate(docs):
        source_text = _normalize_text(str(doc.metadata.get("source", "")))
        text = str(doc.page_content or "")
        parts = [p.strip() for p in re.split(r"[\n\r]+|[•∙]", text) if p.strip()]
        if not parts:
            parts = [" ".join(text.split())]

        for part in parts:
            normalized = _normalize_text(part)
            year_matches = re.findall(r"\b(19\d{2}|20\d{2})\b", normalized)
            if not year_matches:
                continue

            for year in year_matches:
                score = 0
                if any(term in normalized for term in MANUFACTURE_CONTEXT_TERMS):
                    score += 4
                if "annee" in normalized:
                    score += 2
                if any(hint in source_text for hint in MANUFACTURE_SOURCE_HINTS):
                    score += 3
                if any(hint in source_text for hint in MANUAL_SOURCE_HINTS):
                    score -= 4

                score += max(0, 2 - doc_rank)

                year_int = int(year)
                if year_int < 1950 or year_int > 2035:
                    score -= 3

                if score > best_score:
                    best_score = score
                    best_year = year

    if not best_year or best_score < 4:
        return None

    if language == "es":
        return f"El ano de fabricacion del barco es {best_year}."
    if language == "en":
        return f"The boat manufacture year is {best_year}."
    return f"L'annee de fabrication du bateau est {best_year}."


def _extract_insurance_date_answer(question: str, docs: List[Any], language: str) -> Optional[str]:
    question_tokens = set(_tokenize(question))
    insurance_intent = any(token in INSURANCE_TERMS for token in question_tokens)
    date_intent = any(token in DATE_TERMS for token in question_tokens)
    if not (insurance_intent and date_intent):
        return None

    best_date: Optional[str] = None
    best_score = -1

    for doc_rank, doc in enumerate(docs):
        lines = [ln.strip() for ln in str(doc.page_content or "").splitlines() if ln.strip()]
        for idx, line in enumerate(lines):
            context = line
            if idx > 0:
                context = f"{lines[idx - 1]} {context}"
            if idx + 1 < len(lines):
                context = f"{context} {lines[idx + 1]}"

            dates = _find_dates(context)
            if not dates:
                continue

            ctx_tokens = set(_tokenize(context))
            score = 0
            if "generali" in ctx_tokens:
                score += 4
            if any(tok in ctx_tokens for tok in ("effet", "inception", "debut", "commencement")):
                score += 3
            if any(tok in ctx_tokens for tok in ("assurance", "assure", "policy", "police", "contrat")):
                score += 2
            score += max(0, 2 - doc_rank)

            candidate = dates[0]
            if not any(ch.isdigit() for ch in candidate):
                continue

            if score > best_score:
                best_score = score
                best_date = candidate

    if not best_date:
        return None

    if language == "es":
        return f"El barco esta asegurado por GENERALI a partir del {best_date}."
    if language == "en":
        return f"The boat is insured by GENERALI starting from {best_date}."
    return f"Le bateau est assure par GENERALI a partir du {best_date}."


def _extract_emergency_frequency_answer(question: str, docs: List[Any], language: str) -> Optional[str]:
    question_tokens = set(_tokenize(question))
    emergency_intent = any(token in EMERGENCY_TERMS for token in question_tokens)
    frequency_intent = any(token in FREQUENCY_TERMS for token in question_tokens)
    if not (emergency_intent and frequency_intent):
        return None

    best_score = -1
    best_channel: Optional[str] = None
    best_freq: Optional[str] = None

    for doc_rank, doc in enumerate(docs):
        text = str(doc.page_content or "")
        normalized = _normalize_text(text)
        tokens = set(_tokenize(text))

        channel_match = re.search(r"\b(?:canal|channel|ch)\s*(16)\b", normalized, re.IGNORECASE)
        freq_match = re.search(r"\b(156[\.,]8)\s*mhz\b", normalized, re.IGNORECASE)
        if not freq_match:
            freq_match = re.search(r"\b(156[\.,]8)\b", normalized, re.IGNORECASE)

        if not channel_match and not freq_match:
            continue

        score = 0
        if channel_match:
            score += 4
        if freq_match:
            score += 4
        if any(tok in tokens for tok in ("urgence", "detresse", "distress", "mayday", "secours")):
            score += 3
        score += max(0, 2 - doc_rank)

        if score > best_score:
            best_score = score
            best_channel = channel_match.group(1) if channel_match else None
            best_freq = freq_match.group(1).replace('.', ',') if freq_match else None

    if best_score < 0:
        return None

    if best_channel == "16" and not best_freq:
        best_freq = "156,8"

    if best_channel and best_freq:
        if language == "es":
            return f"La frecuencia de urgencias maritimas es el canal {best_channel} ({best_freq} MHz)."
        if language == "en":
            return f"The maritime emergency frequency is channel {best_channel} ({best_freq} MHz)."
        return f"La frequence des urgences maritimes est le canal {best_channel} ({best_freq} MHz)."

    if best_channel:
        if language == "es":
            return f"La frecuencia de urgencias maritimas se transmite por el canal {best_channel}."
        if language == "en":
            return f"The maritime emergency traffic is on channel {best_channel}."
        return f"Les urgences maritimes se transmettent sur le canal {best_channel}."

    if language == "es":
        return f"La frecuencia de urgencias maritimas es {best_freq} MHz."
    if language == "en":
        return f"The maritime emergency frequency is {best_freq} MHz."
    return f"La frequence des urgences maritimes est {best_freq} MHz."


def _clean_equipment_value(raw: str) -> str:
    value = " ".join(str(raw or "").split())
    value = value.strip("-:;,. ")
    return value


def _is_low_signal_value(value: str) -> bool:
    tokens = _tokenize(value)
    if not tokens:
        return True
    if len(tokens) == 1 and tokens[0] in {"quand", "when", "cuando", "si", "if"}:
        return True
    return False


def _extract_value_from_line(line: str) -> Optional[str]:
    if not line:
        return None

    compact = " ".join(str(line).split())
    if not compact:
        return None

    for pattern in (
        r"[:]\s*(.+)$",
        r"[=]\s*(.+)$",
        r"\s+-\s+(.+)$",
    ):
        match = re.search(pattern, compact)
        if match:
            candidate = _clean_equipment_value(match.group(1))
            if 2 <= len(candidate) <= 180:
                return candidate

    columns = [part.strip() for part in re.split(r"\s{2,}", compact) if part.strip()]
    if len(columns) >= 2:
        candidate = _clean_equipment_value(columns[-1])
        if 2 <= len(candidate) <= 180:
            return candidate

    return None


def _extract_chartplotter_value_from_line(line: str) -> Optional[str]:
    if not line:
        return None

    compact = " ".join(str(line).split())
    if not compact:
        return None

    normalized = _normalize_text(compact)
    for brand in CHARTPLOTTER_BRANDS:
        if brand in normalized:
            model_match = re.search(r"\b([a-z]{1,4}\d{2,4}[a-z]{0,2})\b", normalized)
            if model_match:
                model = model_match.group(1)
                return _clean_equipment_value(f"{brand} {model}")
            return _clean_equipment_value(brand)

    return None


def _extract_chartplotter_from_docs(docs: List[Any]) -> Optional[str]:
    best_score = -999
    best_value: Optional[str] = None

    for doc_rank, doc in enumerate(docs):
        source_text = _normalize_text(str(doc.metadata.get("source", "")))
        source_has_equipment_hint = any(hint in source_text for hint in EQUIPMENT_SOURCE_HINTS)
        text_norm = _normalize_text(str(doc.page_content or ""))
        if not text_norm:
            continue

        for brand in CHARTPLOTTER_BRANDS:
            pattern = rf"\b{re.escape(brand)}\s+([a-z]{{1,4}}\d{{2,4}}[a-z]{{0,2}})\b"
            for match in re.finditer(pattern, text_norm):
                model = match.group(1)
                start, end = match.span()
                window = text_norm[max(0, start - 70) : min(len(text_norm), end + 70)]
                chart_ctx = any(term in window for term in ("ecran", "multifonctions", "plotter", "carte", "navigation"))
                radio_ctx = any(term in window for term in RADIO_TERMS)

                score = 0
                if source_has_equipment_hint:
                    score += 3
                if chart_ctx:
                    score += 3
                if radio_ctx:
                    score -= 5
                score -= doc_rank

                if score > best_score:
                    best_score = score
                    best_value = _clean_equipment_value(f"{brand} {model}")

    if best_score < 3:
        return None
    return best_value


def _extract_equipment_value_answer(question: str, docs: List[Any], language: str) -> Optional[str]:
    raw_question = " ".join(str(question or "").split())
    question_tokens = set(_tokenize(raw_question))

    target_tokens = [
        tok
        for tok in _tokenize(raw_question)
        if tok not in STOPWORDS and tok not in BOAT_CONTEXT_TERMS and tok not in EQUIPMENT_TERMS
    ]
    if not target_tokens:
        return None

    target_token_set = set(target_tokens)
    cartography_intent = bool(target_token_set & CARTOGRAPHY_TERMS)
    equipment_intent = bool(question_tokens & EQUIPMENT_TERMS) or cartography_intent

    if cartography_intent:
        chart_value = _extract_chartplotter_from_docs(docs)
        if chart_value:
            if language == "es":
                return f"Valor encontrado para '{raw_question}': {chart_value}."
            if language == "en":
                return f"Value found for '{raw_question}': {chart_value}."
            return f"Valeur trouvee pour '{raw_question}': {chart_value}."

    best_score = -1.0
    best_value: Optional[str] = None

    for doc_rank, doc in enumerate(docs):
        source_text = _normalize_text(str(doc.metadata.get("source", "")))
        source_has_equipment_hint = any(hint in source_text for hint in EQUIPMENT_SOURCE_HINTS)
        lines = [ln.strip() for ln in str(doc.page_content or "").splitlines() if ln.strip()]
        if not lines:
            lines = [part.strip() for part in re.split(r"[\n\r]+", str(doc.page_content or "")) if part.strip()]

        for idx, line in enumerate(lines):
            line_tokens = set(_tokenize(line))
            overlap = len(target_token_set & line_tokens)
            if overlap <= 0:
                continue

            coverage = overlap / max(1, len(target_token_set))
            if len(target_token_set) > 1 and coverage < 0.5:
                continue

            value = _extract_value_from_line(line)
            if cartography_intent and not value:
                value = _extract_chartplotter_value_from_line(line)
            if not value and idx + 1 < len(lines):
                current_tokens = _tokenize(line)
                label_like_line = (
                    len(current_tokens) <= 8
                    or line.endswith(":")
                    or ";" in line
                    or "•" in line
                )
                if not label_like_line:
                    continue
                next_line = lines[idx + 1]
                next_tokens = set(_tokenize(next_line))
                if not (target_token_set & next_tokens):
                    tentative = _clean_equipment_value(next_line)
                    if 2 <= len(tentative) <= 180:
                        value = tentative

            if not value:
                continue
            if _is_low_signal_value(value):
                continue

            if cartography_intent:
                value_normalized = _normalize_text(value)
                looks_like_model = bool(re.search(r"\b[a-z]{1,4}\d{2,4}[a-z]{0,2}\b", value_normalized))
                has_chart_signal = bool(set(_tokenize(value)) & CARTOGRAPHY_TERMS)
                has_brand_signal = any(brand in value_normalized for brand in CHARTPLOTTER_BRANDS)
                line_normalized = _normalize_text(line)
                line_has_chart_signal = bool(set(_tokenize(line)) & CARTOGRAPHY_TERMS)
                if not (looks_like_model or has_chart_signal or has_brand_signal):
                    continue
                # Reject model-like values from non-inventory sources unless the line
                # explicitly carries chartplotter context (e.g. ecran/plotter/navigation).
                if looks_like_model and not (source_has_equipment_hint or line_has_chart_signal or has_brand_signal):
                    continue

            score = coverage * 10.0
            score += max(0.0, 1.5 - (doc_rank * 0.4))
            if equipment_intent and source_has_equipment_hint:
                score += 1.0

            if any(tok in question_tokens for tok in EQUIPMENT_TERMS):
                score += 0.4

            value_tokens = set(_tokenize(value))
            if cartography_intent:
                if value_tokens & CARTOGRAPHY_TERMS:
                    score += 1.0
                if (value_tokens & RADIO_TERMS) and not (value_tokens & CARTOGRAPHY_TERMS):
                    score -= 3.0

            if score > best_score:
                best_score = score
                best_value = value

    if not best_value:
        return None

    min_confidence = 6.5 if cartography_intent else 5.5
    if best_score < min_confidence:
        return None

    if cartography_intent:
        value_norm = _normalize_text(best_value)
        brand_only = value_norm in CHARTPLOTTER_BRANDS
        if brand_only:
            for doc in docs:
                source_norm = _normalize_text(str(doc.metadata.get("source", "")))
                if not any(hint in source_norm for hint in EQUIPMENT_SOURCE_HINTS):
                    continue
                text_norm = _normalize_text(str(doc.page_content or ""))
                for brand in CHARTPLOTTER_BRANDS:
                    if brand not in text_norm:
                        continue
                    model_match = re.search(r"\b([a-z]{1,4}\d{2,4}[a-z]{0,2})\b", text_norm)
                    if model_match:
                        best_value = _clean_equipment_value(f"{brand} {model_match.group(1)}")
                        break
                if _normalize_text(best_value) not in CHARTPLOTTER_BRANDS:
                    break

    if language == "es":
        return f"Valor encontrado para '{raw_question}': {best_value}."
    if language == "en":
        return f"Value found for '{raw_question}': {best_value}."
    return f"Valeur trouvee pour '{raw_question}': {best_value}."


def _score_docs(
    question: str,
    docs: List[Any],
    semantic_rank_map: Optional[Dict[str, int]] = None,
    lexical_rank_map: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    if not docs:
        return []

    question_tokens = set(_tokenize(question))
    insurance_intent = any(token in INSURANCE_TERMS for token in question_tokens)
    identity_intent = any(token in IDENTITY_TERMS for token in question_tokens)
    date_intent = any(token in DATE_TERMS for token in question_tokens)
    emergency_intent = any(token in EMERGENCY_TERMS for token in question_tokens)
    frequency_intent = any(token in FREQUENCY_TERMS for token in question_tokens)
    equipment_intent = bool(question_tokens & EQUIPMENT_TERMS) or bool(question_tokens & CARTOGRAPHY_TERMS)
    manufacture_intent = _is_manufacture_year_intent(question)
    speed_intent = _is_boat_speed_question(question)
    maritime_query_context = bool(question_tokens & MARITIME_TERMS)
    specialized_intent = identity_intent or insurance_intent or date_intent or emergency_intent or frequency_intent
    ranked: List[Dict[str, Any]] = []
    semantic_rank_map = semantic_rank_map or {}
    lexical_rank_map = lexical_rank_map or {}
    semantic_total = max(1, len(semantic_rank_map) - 1)
    lexical_total = max(1, len(lexical_rank_map) - 1)

    for idx, doc in enumerate(docs):
        source = str(doc.metadata.get("source", ""))
        snippet = str(doc.page_content or "")
        haystack = f"{source} {snippet}"
        source_normalized = _normalize_text(source)
        doc_tokens = set(_tokenize(haystack))
        doc_key = _doc_key(doc)

        lexical_overlap = 0.0
        if question_tokens:
            lexical_overlap = len(question_tokens & doc_tokens) / max(1, len(question_tokens))

        if doc_key in semantic_rank_map:
            sem_rank = semantic_rank_map[doc_key]
            semantic_rank_score = (semantic_total - sem_rank) / semantic_total
        else:
            semantic_rank_score = 0.35

        if doc_key in lexical_rank_map:
            lex_rank = lexical_rank_map[doc_key]
            lexical_rank_score = (lexical_total - lex_rank) / lexical_total
        else:
            lexical_rank_score = 0.0

        # Hybrid score: semantic, direct lexical overlap, and lexical rank signal.
        score = 0.45 * semantic_rank_score + 0.35 * lexical_overlap + 0.20 * lexical_rank_score

        # If exact query tokens appear, give a small precision boost (useful for terms like callsign/mmsi).
        exact_token_hits = len(question_tokens & doc_tokens)
        score += min(0.12, exact_token_hits * 0.04)

        maritime_hits = len(MARITIME_TERMS & doc_tokens)
        if maritime_query_context and maritime_hits:
            score += min(0.06, maritime_hits * 0.01)

        identity_hits = 0
        if identity_intent:
            identity_hits = len(IDENTITY_TERMS & doc_tokens)
            score += min(0.22, identity_hits * 0.05)

        insurance_hits = 0
        engine_hits = 0
        date_hits = 0
        emergency_hits = 0
        frequency_hits = 0
        has_date_pattern = bool(_find_dates(haystack))
        has_emergency_frequency_pattern = any(
            pattern.search(_normalize_text(haystack)) for pattern in EMERGENCY_FREQUENCY_PATTERNS
        )
        if insurance_intent:
            insurance_hits = len(INSURANCE_TERMS & doc_tokens)
            engine_hits = len(ENGINE_TERMS & doc_tokens)
            score += min(0.25, insurance_hits * 0.05)
            score -= min(0.12, engine_hits * 0.03)

        if date_intent:
            date_hits = len(DATE_TERMS & doc_tokens)
            score += min(0.18, date_hits * 0.04)
            if has_date_pattern:
                score += 0.08

        if emergency_intent:
            emergency_hits = len(EMERGENCY_TERMS & doc_tokens)
            score += min(0.25, emergency_hits * 0.05)
        if frequency_intent:
            frequency_hits = len(FREQUENCY_TERMS & doc_tokens)
            score += min(0.18, frequency_hits * 0.04)
        if emergency_intent and frequency_intent and has_emergency_frequency_pattern:
            score += 0.14

        if equipment_intent:
            if any(hint in source_normalized for hint in EQUIPMENT_SOURCE_HINTS):
                score += 0.12
            if "notice d'installation" in source_normalized or "volvo" in source_normalized:
                score -= 0.08

        if manufacture_intent:
            manufacture_hits = len(MANUFACTURE_CONTEXT_TERMS & doc_tokens)
            score += min(0.24, manufacture_hits * 0.04)
            if any(hint in source_normalized for hint in MANUFACTURE_SOURCE_HINTS):
                score += 0.22
            if any(hint in source_normalized for hint in MANUAL_SOURCE_HINTS):
                score -= 0.14
            if re.search(r"\b(19\d{2}|20\d{2})\b", _normalize_text(haystack)):
                score += 0.12

        if speed_intent:
            speed_hits = len(SPEED_TERMS & doc_tokens)
            identity_hits = len(BOAT_IDENTITY_TERMS & doc_tokens)
            score += min(0.14, speed_hits * 0.03)
            score += min(0.30, identity_hits * 0.10)
            if any(hint in source_normalized for hint in STRUCTURED_FIELD_SOURCE_HINTS):
                score += 0.18
            if any(hint in source_normalized for hint in MANUAL_SOURCE_HINTS):
                score -= 0.12

        targeted_hits = identity_hits + insurance_hits + date_hits + emergency_hits + frequency_hits
        if specialized_intent and targeted_hits == 0:
            score -= 0.10

        ranked.append(
            {
                "score": float(score),
                "idx": idx,
                "doc": doc,
                "doc_key": doc_key,
                "semantic_rank": semantic_rank_map.get(doc_key),
                "lexical_rank": lexical_rank_map.get(doc_key),
                "semantic_rank_score": float(semantic_rank_score),
                "lexical_rank_score": float(lexical_rank_score),
                "lexical_overlap": float(lexical_overlap),
                "exact_token_hits": int(exact_token_hits),
                "maritime_hits": int(maritime_hits),
                "identity_hits": int(identity_hits),
                "insurance_hits": int(insurance_hits),
                "engine_hits": int(engine_hits),
                "date_hits": int(date_hits),
                "has_date_pattern": bool(has_date_pattern),
                "emergency_hits": int(emergency_hits),
                "frequency_hits": int(frequency_hits),
                "has_emergency_frequency_pattern": bool(has_emergency_frequency_pattern),
            }
        )

    ranked.sort(key=lambda item: (-item["score"], item["idx"]))
    return ranked


def rerank_docs(
    question: str,
    docs: List[Any],
    top_k: int,
    semantic_rank_map: Optional[Dict[str, int]] = None,
    lexical_rank_map: Optional[Dict[str, int]] = None,
) -> List[Any]:
    scored = _score_docs(
        question,
        docs,
        semantic_rank_map=semantic_rank_map,
        lexical_rank_map=lexical_rank_map,
    )
    return [entry["doc"] for entry in scored[: max(1, top_k)]]


def _doc_key(doc: Any) -> str:
    source = str(doc.metadata.get("source", ""))
    snippet = " ".join(str(doc.page_content or "").split())[:220]
    return f"{source}::{snippet}"


def _all_docs_from_vectorstore(vectorstore: Any) -> List[Any]:
    # FAISS backend: iterate stored doc ids from in-memory docstore.
    if hasattr(vectorstore, "index_to_docstore_id") and hasattr(vectorstore, "docstore"):
        docs: List[Any] = []
        for doc_id in vectorstore.index_to_docstore_id.values():
            doc = vectorstore.docstore.search(doc_id)
            if doc is not None:
                docs.append(doc)
        return docs

    # Chroma backend: fetch all stored documents and rebuild Document objects.
    if hasattr(vectorstore, "get"):
        raw = vectorstore.get(include=["documents", "metadatas"])
        documents = raw.get("documents") or []
        metadatas = raw.get("metadatas") or []
        rebuilt = []
        for idx, content in enumerate(documents):
            metadata = metadatas[idx] if idx < len(metadatas) else {}
            rebuilt.append(SimpleNamespace(page_content=content, metadata=metadata))
        return rebuilt

    return []


def _keyword_candidates(question: str, vectorstore: Any, limit: int) -> List[Any]:
    question_tokens = set(_tokenize(question))
    if not question_tokens:
        return []

    insurance_intent = any(token in INSURANCE_TERMS for token in question_tokens)
    date_intent = any(token in DATE_TERMS for token in question_tokens)
    manufacture_intent = _is_manufacture_year_intent(question)
    scored: List[tuple[float, Any]] = []
    for doc in _all_docs_from_vectorstore(vectorstore):
        source = str(getattr(doc, "metadata", {}).get("source", ""))
        snippet = str(getattr(doc, "page_content", "") or "")
        doc_tokens = set(_tokenize(f"{source} {snippet}"))
        if not doc_tokens:
            continue

        overlap = len(question_tokens & doc_tokens) / max(1, len(question_tokens))
        if overlap <= 0:
            continue

        score = overlap
        if insurance_intent:
            insurance_hits = len(INSURANCE_TERMS & doc_tokens)
            engine_hits = len(ENGINE_TERMS & doc_tokens)
            score += min(0.3, insurance_hits * 0.06)
            score -= min(0.12, engine_hits * 0.03)
        if manufacture_intent:
            source_normalized = _normalize_text(source)
            manufacture_hits = len(MANUFACTURE_CONTEXT_TERMS & doc_tokens)
            score += min(0.24, manufacture_hits * 0.04)
            if any(hint in source_normalized for hint in MANUFACTURE_SOURCE_HINTS):
                score += 0.22
            if any(hint in source_normalized for hint in MANUAL_SOURCE_HINTS):
                score -= 0.14
            if re.search(r"\b(19\d{2}|20\d{2})\b", _normalize_text(snippet)):
                score += 0.12
        scored.append((score, doc))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [doc for _, doc in scored[: max(1, limit)]]


def hybrid_retrieve_docs_debug(
    question: str,
    vectorstore: Any,
    top_k: int,
    candidate_k: Optional[int] = None,
) -> Tuple[List[Any], List[Dict[str, Any]]]:
    initial_k = max(top_k, min(top_k * 6, int(candidate_k or 24)))
    semantic_docs = vectorstore.similarity_search(question, k=initial_k)
    lexical_docs = _keyword_candidates(question, vectorstore, limit=max(top_k * 4, 10))

    merged: List[Any] = []
    seen: set[str] = set()
    for doc in semantic_docs + lexical_docs:
        key = _doc_key(doc)
        if key in seen:
            continue
        seen.add(key)
        merged.append(doc)

    semantic_rank_map = {_doc_key(doc): idx for idx, doc in enumerate(semantic_docs)}
    lexical_rank_map = {_doc_key(doc): idx for idx, doc in enumerate(lexical_docs)}

    scored = _score_docs(
        question,
        merged,
        semantic_rank_map=semantic_rank_map,
        lexical_rank_map=lexical_rank_map,
    )

    question_tokens = set(_tokenize(question))
    identity_intent = any(token in IDENTITY_TERMS for token in question_tokens)
    insurance_intent = any(token in INSURANCE_TERMS for token in question_tokens)
    date_intent = any(token in DATE_TERMS for token in question_tokens)
    emergency_intent = any(token in EMERGENCY_TERMS for token in question_tokens)
    frequency_intent = any(token in FREQUENCY_TERMS for token in question_tokens)

    filtered_scored = scored
    if identity_intent:
        identity_first = [
            item for item in scored if item["identity_hits"] > 0 or item["lexical_overlap"] >= 0.4
        ]
        if identity_first:
            filtered_scored = identity_first

    if insurance_intent:
        insurance_first = [
            item
            for item in filtered_scored
            if item["insurance_hits"] > 0 or item["lexical_overlap"] >= 0.3
        ]
        if insurance_first:
            filtered_scored = insurance_first

    if insurance_intent and date_intent:
        insurance_date_first = [
            item
            for item in filtered_scored
            if item["has_date_pattern"] or item["date_hits"] > 0
        ]
        if insurance_date_first:
            filtered_scored = insurance_date_first

    if emergency_intent and frequency_intent:
        emergency_frequency_first = [
            item
            for item in filtered_scored
            if (
                item["has_emergency_frequency_pattern"]
                or (item["emergency_hits"] > 0 and item["frequency_hits"] > 0)
            )
        ]
        if emergency_frequency_first:
            filtered_scored = emergency_frequency_first

    top_scored = filtered_scored[: max(1, top_k)]
    top_docs = [entry["doc"] for entry in top_scored]
    debug_rows: List[Dict[str, Any]] = []
    for entry in top_scored:
        doc = entry["doc"]
        source = str(doc.metadata.get("source", "unknown"))
        snippet = " ".join(str(doc.page_content or "").split())[:260]
        debug_rows.append(
            {
                "source": source,
                "snippet": snippet,
                "score": entry["score"],
                "semantic_rank": entry["semantic_rank"],
                "lexical_rank": entry["lexical_rank"],
                "semantic_rank_score": entry["semantic_rank_score"],
                "lexical_rank_score": entry["lexical_rank_score"],
                "lexical_overlap": entry["lexical_overlap"],
                "exact_token_hits": entry["exact_token_hits"],
                "maritime_hits": entry["maritime_hits"],
                "identity_hits": entry["identity_hits"],
                "insurance_hits": entry["insurance_hits"],
                "engine_hits": entry["engine_hits"],
                "date_hits": entry["date_hits"],
                "has_date_pattern": entry["has_date_pattern"],
                "emergency_hits": entry["emergency_hits"],
                "frequency_hits": entry["frequency_hits"],
                "has_emergency_frequency_pattern": entry["has_emergency_frequency_pattern"],
            }
        )

    return top_docs, debug_rows


def hybrid_retrieve_docs(question: str, vectorstore: Any, top_k: int) -> List[Any]:
    docs, _ = hybrid_retrieve_docs_debug(question, vectorstore, top_k)
    return docs


app = FastAPI(title="CEIBO RAG Local API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"ok": "true"}


@app.post("/query")
def query(payload: QueryPayload) -> Dict[str, Any]:
    question = str(payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    language = detect_language(payload.language, question)
    retrieval_question = _build_retrieval_question(question)

    try:
        index_dir = resolve_index_dir(payload.index_dir)
        loaded = load_vectorstore(index_dir, payload.backend)
        vectorstore = loaded["vectorstore"]
        target_top_k = max(1, int(payload.top_k or 4))
        docs = hybrid_retrieve_docs(retrieval_question, vectorstore, target_top_k)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    sources = format_docs(docs)
    extracted = _extract_emergency_frequency_answer(question, docs, language)
    if not extracted:
        extracted = _extract_insurance_date_answer(question, docs, language)
    if not extracted:
        extracted = _extract_structured_field_answer(question, docs, language)
    if not extracted:
        extracted = _extract_speed_answer(question, docs, language)
    if not extracted:
        extracted = _extract_manufacture_year_answer(question, docs, language)
    if not extracted and _is_equipment_question(question):
        extracted = _extract_equipment_value_answer(question, docs, language)
    synthesis = extracted or "\n\n".join(
        f"[{i}] {item['snippet']}" for i, item in enumerate(sources, start=1)
    )

    return {
        "question": question,
        "language": language,
        "backend": loaded["backend"],
        "index_dir": str(index_dir),
        "answer": synthesis or localized_no_result(language),
        "sources": sources,
    }


@app.post("/query-debug")
def query_debug(payload: DebugQueryPayload) -> Dict[str, Any]:
    question = str(payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    language = detect_language(payload.language, question)
    retrieval_question = _build_retrieval_question(question)

    try:
        index_dir = resolve_index_dir(payload.index_dir)
        loaded = load_vectorstore(index_dir, payload.backend)
        vectorstore = loaded["vectorstore"]
        target_top_k = max(1, int(payload.top_k or 4))
        docs, debug_rows = hybrid_retrieve_docs_debug(
            retrieval_question,
            vectorstore,
            target_top_k,
            candidate_k=payload.candidate_k,
        )
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    sources = format_docs(docs)
    extracted = _extract_emergency_frequency_answer(question, docs, language)
    if not extracted:
        extracted = _extract_insurance_date_answer(question, docs, language)
    if not extracted:
        extracted = _extract_structured_field_answer(question, docs, language)
    if not extracted:
        extracted = _extract_speed_answer(question, docs, language)
    if not extracted:
        extracted = _extract_manufacture_year_answer(question, docs, language)
    if not extracted and _is_equipment_question(question):
        extracted = _extract_equipment_value_answer(question, docs, language)
    synthesis = extracted or "\n\n".join(
        f"[{i}] {item['snippet']}" for i, item in enumerate(sources, start=1)
    )

    return {
        "question": question,
        "language": language,
        "backend": loaded["backend"],
        "index_dir": str(index_dir),
        "answer": synthesis or localized_no_result(language),
        "sources": sources,
        "ranking_debug": debug_rows,
    }


@app.post("/query-llm")
def query_llm(payload: LlmQueryPayload) -> Dict[str, Any]:
    question = str(payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    language = detect_language(payload.language, question)
    retrieval_question = _build_retrieval_question(question)

    try:
        index_dir = resolve_index_dir(payload.index_dir)
        loaded = load_vectorstore(index_dir, payload.backend)
        vectorstore = loaded["vectorstore"]
        target_top_k = max(1, int(payload.top_k or 6))
        docs = hybrid_retrieve_docs(retrieval_question, vectorstore, target_top_k)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    sources = format_docs(docs)

    local_answer = _extract_emergency_frequency_answer(question, docs, language)
    if not local_answer:
        local_answer = _extract_insurance_date_answer(question, docs, language)
    if not local_answer:
        local_answer = _extract_structured_field_answer(question, docs, language)
    if not local_answer:
        local_answer = _extract_speed_answer(question, docs, language)
    if not local_answer:
        local_answer = _extract_manufacture_year_answer(question, docs, language)
    if not local_answer and _is_equipment_question(question):
        local_answer = _extract_equipment_value_answer(question, docs, language)

    mode = str(payload.mode or "hybrid").strip().lower()
    if mode not in {"local", "external", "hybrid"}:
        mode = "hybrid"

    response_style = str(payload.response_style or "concise").strip().lower()
    if response_style not in {"concise", "detailed"}:
        response_style = "concise"

    external_answer: Optional[str] = None
    final_answer = local_answer

    if mode == "external":
        external_answer = _call_external_llm(payload, language, sources)
        if _looks_like_context_refusal(external_answer) or _looks_like_off_topic_equipment_answer(question, external_answer):
            external_answer = _general_fallback_answer(question, language)
        final_answer = external_answer
    elif mode == "hybrid":
        if local_answer and response_style == "concise":
            final_answer = local_answer
        else:
            external_answer = _call_external_llm(payload, language, sources)
            if _looks_like_context_refusal(external_answer) or _looks_like_off_topic_equipment_answer(question, external_answer):
                external_answer = _general_fallback_answer(question, language)
            if local_answer and response_style == "detailed":
                if language == "es":
                    final_answer = (
                        "Respuesta directa (RAG local):\n"
                        f"{local_answer}\n\n"
                        "Complemento detallado:\n"
                        f"{external_answer}"
                    )
                elif language == "en":
                    final_answer = (
                        "Direct answer (local RAG):\n"
                        f"{local_answer}\n\n"
                        "Detailed complement:\n"
                        f"{external_answer}"
                    )
                else:
                    final_answer = (
                        "Reponse directe (RAG local):\n"
                        f"{local_answer}\n\n"
                        "Complement detaille:\n"
                        f"{external_answer}"
                    )
            else:
                final_answer = external_answer

    if not final_answer:
        final_answer = "\n\n".join(f"[{i}] {item['snippet']}" for i, item in enumerate(sources, start=1))

    return {
        "question": question,
        "language": language,
        "mode": mode,
        "response_style": response_style,
        "provider": payload.provider,
        "backend": loaded["backend"],
        "index_dir": str(index_dir),
        "answer": final_answer or localized_no_result(language),
        "local_answer": local_answer,
        "external_answer": external_answer,
        "sources": sources,
    }


@app.post("/build-index")
def build_index(payload: BuildPayload) -> Dict[str, Any]:
    if not BUILD_INDEX_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Index build already running")

    try:
        script_dir = Path(__file__).resolve().parent
        repo_root = script_dir.parent
        script_path = script_dir / "build_index.py"
        if not script_path.exists():
            raise HTTPException(status_code=500, detail=f"Missing script: {script_path}")

        docs_dir_raw = str(payload.docs_dir or "./rag/documents")
        out_dir_raw = str(payload.out_dir or "./rag/index")

        docs_dir_path = Path(docs_dir_raw).expanduser()
        if not docs_dir_path.is_absolute():
            docs_dir_path = (repo_root / docs_dir_path).resolve()
        if not docs_dir_path.exists() or not docs_dir_path.is_dir():
            raise HTTPException(status_code=400, detail=f"docs_dir not found: {docs_dir_path}")

        out_dir_path = Path(out_dir_raw).expanduser()
        if not out_dir_path.is_absolute():
            out_dir_path = (repo_root / out_dir_path).resolve()

        cmd = [
            sys.executable,
            str(script_path),
            "--docs-dir",
            str(docs_dir_path),
            "--backend",
            payload.backend if payload.backend in {"chroma", "faiss"} else "faiss",
            "--out-dir",
            str(out_dir_path),
            "--chunk-size",
            str(max(300, int(payload.chunk_size or 1000))),
            "--chunk-overlap",
            str(max(0, int(payload.chunk_overlap or 150))),
        ]
        if payload.embeddings_model:
            cmd.extend(["--embeddings-model", str(payload.embeddings_model)])

        completed = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if completed.returncode != 0:
            details = stderr or stdout or "Unknown build_index.py failure"
            raise HTTPException(status_code=500, detail=details)

        meta_path = out_dir_path / "index_meta.json"
        meta: Dict[str, Any] = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))

        return {
            "ok": True,
            "meta": meta,
            "stdout": stdout,
        }
    finally:
        BUILD_INDEX_LOCK.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CEIBO local RAG HTTP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    uvicorn.run("server:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
