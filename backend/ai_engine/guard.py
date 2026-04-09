from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# A small database of common interview answers
COMMON_ANSWERS = [
    "I'm a hard worker who always goes the extra mile.",
    "My greatest weakness is that I work too hard.",
    "I'm a team player and I love collaborating with others.",
    "In five years, I see myself as a leader in this company.",
    "I thrive in fast-paced environments and love solving complex problems.",
]

def check_plagiarism(candidate_answer):
    if not candidate_answer:
        return 0.0
    
    all_texts = [candidate_answer] + COMMON_ANSWERS
    vectorizer = TfidfVectorizer().fit_transform(all_texts)
    vectors = vectorizer.toarray()
    
    # Compare candidate answer (index 0) with all common answers
    similarities = cosine_similarity([vectors[0]], vectors[1:])
    max_similarity = similarities.max()
    
    return float(max_similarity)

def is_ai_generated(text):
    # This would typically call Originality.ai or GPTZero
    # For now, a placeholder logic or simple length/complexity heuristic
    # Real implementation would use an API key
    return False 
