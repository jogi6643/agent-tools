# store_chroma.py -- Chroma-backed vector store
import os
import chromadb

from llm import client
from chunker import chunk_document

EMBED_MODEL = "nomic-embed-text"
DOC_PATH = "docs/shopkart_policies.md"
CHROMA_DIR = "chroma_db"
COLLECTION = "shopkart_policies"


def embed(text: str) -> list[float]:
    """Convert text into a vector using OUR model, not Chroma's default."""
    response = client.embeddings.create(model=EMBED_MODEL, input=text)
    return response.data[0].embedding


def get_collection():
    """Open (or create) the persistent Chroma collection."""
    db = chromadb.PersistentClient(path=CHROMA_DIR)
    return db.get_or_create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def build_index() -> int:
    """INDEXING: chunk the document and upsert every chunk."""
    with open(DOC_PATH, encoding="utf-8") as f:
        text = f.read()

    source = os.path.basename(DOC_PATH)
    chunks = chunk_document(text, source=source)
    collection = get_collection()

    collection.upsert(
        ids=[f"{source}#{i}" for i in range(len(chunks))],
        documents=[c["text"] for c in chunks],
        embeddings=[embed(c["text"]) for c in chunks],
        metadatas=[
            {"source": c["source"], "section": c["section"]} for c in chunks
        ],
    )

    return collection.count()


def search(query: str, k: int = 3, section: str | None = None) -> list[dict]:
    """QUERY: semantic search, optionally filtered to one section."""
    collection = get_collection()

    results = collection.query(
        query_embeddings=[embed(query)],
        n_results=k,
        where={"section": section} if section else None,
    )

    hits = []
    for text, meta, distance in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        hits.append({
            "text": text,
            "section": meta["section"],
            "source": meta["source"],
            "score": 1 - distance,      # cosine DISTANCE -> similarity
        })

    return hits


if __name__ == "__main__":
    count = build_index()
    print(f"collection: {count} chunks\n")

    question = "how do I get my money back?"

    print(f"Q: {question}")
    print("--- normal search ---")
    for hit in search(question):
        print(f"  {hit['score']:.3f}  [{hit['section']}]")

    print("\n--- filtered: section = Warranty only ---")
    for hit in search(question, section="Warranty"):
        print(f"  {hit['score']:.3f}  [{hit['section']}]")