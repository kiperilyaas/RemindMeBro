"""
Vector store locale basato su ChromaDB.

Indicizza avvisi e messaggi (Moodle/Teams/Email) per la ricerca
semantica usata dal chatbot RAG.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

import chromadb

from app.config import settings

logger = logging.getLogger(__name__)

_client = None
_collection = None
_lock = threading.Lock()


class _OllamaEmbeddingFunction:
    """
    Embedding function minimale che usa Ollama in locale.
    Attivabile con CHROMA_EMBEDDING=ollama (alternativa 100% offline al modello ONNX).
    """

    def __init__(self, model: str, host: str) -> None:
        import ollama

        self._client = ollama.Client(host=host)
        self._model = model

    def __call__(self, input: List[str]) -> List[List[float]]:  # noqa: A002 (firma richiesta da Chroma)
        response = self._client.embed(model=self._model, input=list(input))
        return [list(vec) for vec in response["embeddings"]]

    # Chroma >= 0.6 usa questi metodi per identificare la funzione
    @staticmethod
    def name() -> str:
        return "academic_hub_ollama"

    def embed_documents(self, input: List[str]) -> List[List[float]]:  # noqa: A002
        return self(input)

    def embed_query(self, input: List[str]) -> List[List[float]]:  # noqa: A002
        return self(input)


def _build_client():
    """Crea il client Chroma (persistente su disco o in-memory)."""
    if settings.CHROMA_MODE.lower() == "memory":
        logger.info("ChromaDB in modalità in-memory")
        return chromadb.EphemeralClient()
    logger.info("ChromaDB persistente in %s", settings.CHROMA_PATH)
    return chromadb.PersistentClient(path=settings.CHROMA_PATH)


def get_collection():
    """Ritorna (creandola al primo uso) la collezione `academic_announcements`."""
    global _client, _collection
    if _collection is not None:
        return _collection
    with _lock:
        if _collection is None:
            _client = _build_client()
            kwargs: Dict[str, Any] = {
                "name": settings.CHROMA_COLLECTION,
                "metadata": {"hnsw:space": "cosine"},
            }
            if settings.CHROMA_EMBEDDING.lower() == "ollama":
                kwargs["embedding_function"] = _OllamaEmbeddingFunction(
                    settings.OLLAMA_EMBED_MODEL, settings.OLLAMA_HOST
                )
            _collection = _client.get_or_create_collection(**kwargs)
    return _collection


def _sanitize_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Chroma accetta solo str/int/float/bool: converte il resto e scarta i None."""
    clean: Dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            clean[key] = value
        else:
            clean[key] = str(value)
    return clean


def add_announcement_to_vector_db(id: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> None:  # noqa: A002
    """
    Indicizza un testo nel vector DB.

    Usa `upsert`, quindi rieseguire la sync non crea duplicati.
    """
    if not text or not text.strip():
        return
    collection = get_collection()
    collection.upsert(ids=[str(id)], documents=[text], metadatas=[_sanitize_metadata(metadata) or {"source": "unknown"}])


def query_relevant_context(query_text: str, n_results: int = 3) -> List[Dict[str, Any]]:
    """
    Ricerca semantica: ritorna i frammenti più rilevanti per la query.

    Output: lista di dict {id, text, metadata, distance}, ordinata per rilevanza.
    """
    collection = get_collection()
    total = collection.count()
    if total == 0:
        return []
    result = collection.query(query_texts=[query_text], n_results=min(n_results, total))

    ids = (result.get("ids") or [[]])[0]
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    dists = (result.get("distances") or [[]])[0]

    hits: List[Dict[str, Any]] = []
    for i, doc_id in enumerate(ids):
        hits.append(
            {
                "id": doc_id,
                "text": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if i < len(metas) and metas[i] else {},
                "distance": float(dists[i]) if i < len(dists) and dists[i] is not None else None,
            }
        )
    return hits


def reset_collection() -> None:
    """Svuota la collezione (usato quando il DB demo viene rigenerato)."""
    global _collection
    get_collection()  # assicura che il client sia inizializzato
    with _lock:
        _client.delete_collection(settings.CHROMA_COLLECTION)
        _collection = None
    logger.info("Collezione ChromaDB '%s' azzerata", settings.CHROMA_COLLECTION)


def count_documents() -> int:
    """Numero di documenti indicizzati (utile per health-check e riepiloghi)."""
    try:
        return get_collection().count()
    except Exception:  # pragma: no cover - solo diagnostica
        return 0
