import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

class RAGRetriever:
    def __init__(self, model_name='all-MiniLM-L6-v2'):
        """
        Initialize the embedding model and the embedding properties.
        'all-MiniLM-L6-v2' is a lightweight dense retrieval model ideal for FAISS.
        """
        self.encoder = SentenceTransformer(model_name)
        self.dimension = self.encoder.get_embedding_dimension()
        self.index = None
        self.chunks = []
        
    def chunk_text(self, text, chunk_size=200, overlap=50):
        """
        Simple overlapping word chunking.
        """
        words = text.split()
        chunks = []
        for i in range(0, len(words), chunk_size - overlap):
            chunk = " ".join(words[i:i + chunk_size])
            chunks.append(chunk)
            if i + chunk_size >= len(words):
                break
        return chunks

    def build_index(self, resume_text, jd_text):
        """
        Build a FAISS index from the Resume and JD texts.
        """
        resume_chunks = self.chunk_text(f"[RESUME CONTEXT] {resume_text}")
        jd_chunks = self.chunk_text(f"[JD CONTEXT] {jd_text}")
        
        self.chunks = resume_chunks + jd_chunks
        
        if not self.chunks:
            return
            
        # Generate embeddings for all chunks
        embeddings = self.encoder.encode(self.chunks)
        
        # Convert to float32 numpy array as FAISS requires
        embeddings = np.array(embeddings).astype('float32')
        
        # Initialize L2 distance based FAISS Index
        self.index = faiss.IndexFlatL2(self.dimension)
        self.index.add(embeddings)
        
    def retrieve(self, query, top_k=3):
        """
        Retrieve the top-K most relevant context chunks for a given query.
        """
        if not self.index or not self.chunks:
            return "No context available."
            
        query_embedding = self.encoder.encode([query])
        query_embedding = np.array(query_embedding).astype('float32')
        
        # Search the index
        distances, indices = self.index.search(query_embedding, top_k)
        
        results = []
        for idx in indices[0]:
            if idx < len(self.chunks) and idx >= 0:
                results.append(self.chunks[idx])
                
        return "\n\n".join(results)
