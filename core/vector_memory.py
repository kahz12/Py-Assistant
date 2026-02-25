"""
core/vector_memory.py -- Memoria vectorial semantica (Feature 8).

Permite busqueda semantica sobre las notas del vault usando ChromaDB
con embeddings de sentence-transformers o OpenAI.

Cuando se guarda una nota con `guardar_nota`, tambien se embebe
automaticamente para busqueda semántica via `buscar_semantico`.

Dependencias:
    pip install chromadb>=0.5 sentence-transformers>=3.0

Uso:
    vm = VectorMemory(vault_path)
    vm.add("mi nota de texto", metadata={"source": "guardar_nota"})
    results = vm.search("tema relacionado", n_results=5)
"""
from pathlib import Path
from typing import Optional
from loguru import logger

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer
    ST_AVAILABLE = True
except ImportError:
    ST_AVAILABLE = False

_MODEL_NAME = "all-MiniLM-L6-v2"   # ~80MB, rapido en CPU


class VectorMemory:
    """
    Wrapper sobre ChromaDB para memoria semantica del asistente.

    Usa sentence-transformers localmente para embeber el texto.
    Si sentence-transformers no esta disponible, guarda el texto
    sin embedding (solo keyword fallback).

    Atributos:
        _client: Cliente ChromaDB persistente.
        _collection: Coleccion 'notes' del vault.
        _model: Modelo de embeddings (SentenceTransformer o None).
    """

    def __init__(self, vault_path: Path):
        self._client = None
        self._collection = None
        self._model = None
        self._available = False

        if not CHROMA_AVAILABLE:
            logger.warning(
                "[VectorMemory] chromadb no instalado. "
                "Instala con: pip install 'chromadb>=0.5'"
            )
            return

        chroma_dir = vault_path / "chroma"
        chroma_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._client = chromadb.PersistentClient(
                path=str(chroma_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name="notes",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(f"[VectorMemory] ChromaDB inicializado. Items: {self._collection.count()}")
            self._available = True
        except Exception as e:
            logger.error(f"[VectorMemory] Error inicializando ChromaDB: {e}")
            return

        if ST_AVAILABLE:
            try:
                self._model = SentenceTransformer(_MODEL_NAME)
                logger.info(f"[VectorMemory] Modelo '{_MODEL_NAME}' cargado.")
            except Exception as e:
                logger.warning(f"[VectorMemory] No se pudo cargar el modelo: {e}")
        else:
            logger.warning(
                "[VectorMemory] sentence-transformers no instalado. "
                "Busqueda semantica desactivada. "
                "Instala con: pip install 'sentence-transformers>=3.0'"
            )

    @property
    def available(self) -> bool:
        """True si ChromaDB esta listo para operar."""
        return self._available

    def _embed(self, text: str) -> Optional[list[float]]:
        """Genera el vector embedding de un texto."""
        if self._model:
            return self._model.encode(text).tolist()
        return None

    def add(self, text: str, doc_id: Optional[str] = None, metadata: Optional[dict] = None) -> bool:
        """
        Añade un documento a la coleccion vectorial.

        Args:
            text: Texto a indexar.
            doc_id: ID unico del documento (se genera uno si no se provee).
            metadata: Metadatos adicionales (fuente, fecha, etc.).

        Returns:
            True si se indexo correctamente.
        """
        if not self._available or not self._collection:
            return False

        import uuid, time
        doc_id = doc_id or f"note_{uuid.uuid4().hex[:12]}"
        metadata = {**(metadata or {}), "ts": time.time(), "text_preview": text[:100]}

        try:
            embedding = self._embed(text)
            if embedding:
                self._collection.upsert(
                    ids=[doc_id],
                    documents=[text],
                    embeddings=[embedding],
                    metadatas=[metadata],
                )
            else:
                # Sin modelo: usar ChromaDB con embeddings por defecto
                self._collection.upsert(
                    ids=[doc_id],
                    documents=[text],
                    metadatas=[metadata],
                )
            logger.debug(f"[VectorMemory] Indexado: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"[VectorMemory] Error indexando documento: {e}")
            return False

    def search(self, query: str, n_results: int = 5) -> list[dict]:
        """
        Busqueda semantica en la coleccion de notas.

        Args:
            query: Texto de consulta en lenguaje natural.
            n_results: Numero maximo de resultados.

        Returns:
            Lista de dicts con {text, score, metadata}.
        """
        if not self._available or not self._collection:
            return []
        if self._collection.count() == 0:
            return []

        try:
            n = min(n_results, self._collection.count())
            embedding = self._embed(query)
            if embedding:
                results = self._collection.query(
                    query_embeddings=[embedding],
                    n_results=n,
                    include=["documents", "distances", "metadatas"],
                )
            else:
                results = self._collection.query(
                    query_texts=[query],
                    n_results=n,
                    include=["documents", "distances", "metadatas"],
                )

            output = []
            docs = results.get("documents", [[]])[0]
            dists = results.get("distances", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            for doc, dist, meta in zip(docs, dists, metas):
                output.append({
                    "text": doc,
                    "score": round(1 - dist, 4),   # coseno: 1=identico, 0=distante
                    "metadata": meta,
                })
            return output
        except Exception as e:
            logger.error(f"[VectorMemory] Error en busqueda: {e}")
            return []

    def delete(self, doc_id: str) -> bool:
        """Elimina un documento del indice vectorial."""
        if not self._available or not self._collection:
            return False
        try:
            self._collection.delete(ids=[doc_id])
            return True
        except Exception as e:
            logger.error(f"[VectorMemory] Error eliminando '{doc_id}': {e}")
            return False

    def count(self) -> int:
        """Retorna el numero de documentos indexados."""
        if not self._available or not self._collection:
            return 0
        return self._collection.count()
