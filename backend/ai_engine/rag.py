"""RAG over the job description and resume, with nothing running locally.

Semantic: Gemini embeddings ranked by cosine similarity, rebuilt per request (two small docs, ~10 vectors,
so no vector DB or numpy). Falls back to keyword ranking (simplified BM25) if Gemini is unset, rate-limited (free tier resets daily) or fails.
ponytail: re-embeds both docs every round; cache vectors on the session if embedding calls get costly.
"""
import logging
import math
import os
import re
from collections import Counter

from langchain_google_genai import GoogleGenerativeAIEmbeddings

log = logging.getLogger(__name__)

EMBED_MODEL = "gemini-embedding-001"

STOP_WORDS = set("""
a an and are as at be by for from has have in is it of on or that the this to was were will with you your
we our they their i my me he she his her its not but if then than so such can could should would may
""".split())


def _tokens(text):
    words = (w.strip('.') for w in re.findall(r"[a-z0-9+#.]+", text.lower()))
    return [w for w in words if len(w) > 1 and w not in STOP_WORDS]


def chunk_text(text, chunk_size=80, overlap=20):
    words = text.split()
    return [" ".join(words[i:i + chunk_size]) for i in range(0, max(len(words) - overlap, 1), chunk_size - overlap)] if words else []


def _top_chunks(query_terms, text, top_k):
    chunks = chunk_text(text)
    docs = [Counter(_tokens(c)) for c in chunks]
    df = Counter(t for d in docs for t in d)
    n = len(docs)

    def score(d):
        return sum(d[t] / (d[t] + 1.2) * math.log(1 + n / df[t]) for t in query_terms if t in d)

    ranked = sorted(range(n), key=lambda i: score(docs[i]), reverse=True)[:top_k]
    # Keep document order so excerpts read naturally; fall back to the opening chunk if nothing matches
    hits = sorted(i for i in ranked if score(docs[i]) > 0) or [0][:n]
    return "\n...\n".join(chunks[i] for i in hits)


def _semantic(query, resume_text, jd_text, top_k):
    key = os.getenv("GOOGLE_API_KEY", "")
    if not key or "your_" in key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    chunks = {"resume": chunk_text(resume_text or ""), "jd": chunk_text(jd_text or "")}
    texts = chunks["resume"] + chunks["jd"]
    if not texts:
        return "", ""

    embeddings = GoogleGenerativeAIEmbeddings(model=EMBED_MODEL, google_api_key=key)
    vectors = embeddings.embed_documents(texts)  # one batched call for both documents
    query_vector = embeddings.embed_query(query)

    def cosine(v):
        return sum(a * b for a, b in zip(v, query_vector)) / ((math.hypot(*v) * math.hypot(*query_vector)) or 1)

    split = len(chunks["resume"])
    def best(source, vecs):
        ranked = sorted(range(len(vecs)), key=lambda i: cosine(vecs[i]), reverse=True)[:top_k]
        return "\n...\n".join(chunks[source][i] for i in sorted(ranked))  # document order reads naturally

    return best("resume", vectors[:split]), best("jd", vectors[split:])


def retrieve(query, resume_text, jd_text, top_k=2):
    """Return (resume_excerpts, jd_excerpts): the chunks of each document most relevant to the query."""
    try:
        return _semantic(query, resume_text, jd_text, top_k)
    except Exception as e:
        log.warning("Semantic retrieval unavailable (%s); using keyword ranking", e)
    terms = set(_tokens(query))
    return _top_chunks(terms, resume_text or "", top_k), _top_chunks(terms, jd_text or "", top_k)
