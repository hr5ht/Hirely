import re
import spacy
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    print("Warning: 'en_core_web_sm' not found.")
    nlp = None
def preprocess_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r'http\S+|www\S+|https\S+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\S+@\S+', '', text)
    text = re.sub(r"[•▪●–—★]", " ", text)
    text = re.sub(r"[^a-z0-9\s\+\#\.\_\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if nlp:
        doc = nlp(text)
        tokens = [
            token.lemma_ if token.lemma_ != "-PRON-" else token.text
            for token in doc
            if not token.is_stop and (token.is_alpha or any(c in token.text for c in '+#.'))
        ]
        return " ".join(tokens)
    return text