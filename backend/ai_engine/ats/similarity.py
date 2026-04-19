import logging
from sklearn.metrics.pairwise import cosine_similarity
logger = logging.getLogger(__name__)
_model = None
try:
    from sentence_transformers import SentenceTransformer
    _model = SentenceTransformer('all-MiniLM-L6-v2')
    logger.info("Sentence Transformer model loaded successfully.")
except ImportError:
    logger.warning("sentence-transformers not installed. Falling back to TF-IDF.")
except Exception as e:
    logger.warning(f"Failed to load Sentence Transformer model: {e}.")
def calculate_similarity(resume_text: str, jd_text: str) -> float:
    if not resume_text or not jd_text:
        return 0.0
    if _model is not None:
        try:
            embeddings = _model.encode([resume_text, jd_text], convert_to_numpy=True)
            score = cosine_similarity([embeddings[0]], [embeddings[1]])[0][0]
            return round(float(score) * 100, 2)
        except Exception as e:
            logger.error(f"Sentence Transformer similarity failed: {e}.")
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        vectorizer = TfidfVectorizer()
        vectors = vectorizer.fit_transform([resume_text, jd_text])
        score = cosine_similarity(vectors[0], vectors[1])[0][0]
        return round(float(score) * 100, 2)
    except Exception as e:
        logger.error(f"TF-IDF similarity calculation also failed: {e}")
        return 0.0
