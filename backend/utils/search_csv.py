# File: backend/utils/search_csv.py

import os
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from scipy.sparse import load_npz
import pandas as pd

def load_cached_data(cache_dir: str):
    """
    Loads the cached TF-IDF matrix and metadata.

    Args:
        cache_dir (str): Directory where the cache is stored.

    Returns:
        tuple: TF-IDF matrix, vocabulary, IDF values, and document data.
    """
    # Load sparse TF-IDF matrix
    tfidf_matrix = load_npz(os.path.join(cache_dir, "tfidf_matrix.npz"))

    # Load TF-IDF metadata (vocabulary and IDF values)
    metadata = np.load(os.path.join(cache_dir, "tfidf_metadata.npz"), allow_pickle=True)
    vocabulary = metadata['vocabulary'].item()
    idf_values = metadata['idf_values']

    # Load CSV data for document information
    csv_file_path = 'path/to/output/csv/pdfs.csv'  # Replace with the path to the original CSV
    df = pd.read_csv(csv_file_path)

    return tfidf_matrix, vocabulary, idf_values, df

def search_query(query: str, tfidf_matrix, df, vocabulary):
    """
    Searches for documents that match the query using the TF-IDF matrix.

    Args:
        query (str): Search query.
        tfidf_matrix (scipy.sparse.csr_matrix): The TF-IDF matrix.
        df (pandas.DataFrame): The original CSV data.
        vocabulary (dict): The TF-IDF vocabulary.

    Returns:
        list: Matching documents with their similarity scores.
    """
    # Vectorize the query
    from sklearn.feature_extraction.text import TfidfVectorizer
    vectorizer = TfidfVectorizer(vocabulary=vocabulary)
    query_vec = vectorizer.fit_transform([query])

    # Calculate cosine similarity between query vector and TF-IDF matrix
    similarity_scores = cosine_similarity(query_vec, tfidf_matrix).flatten()

    # Get top results
    top_indices = similarity_scores.argsort()[::-1][:5]  # Get top 5 results

    results = []
    for idx in top_indices:
        results.append({
            'filename': df.iloc[idx]['filename'],
            'content': df.iloc[idx]['content'],
            'similarity': similarity_scores[idx]
        })
    
    return results

if __name__ == "__main__":
    query = "your search query"  # Replace with your search query
    cache_dir = 'path/to/cache/dir'  # Replace with the cache directory

    # Load the cached data
    tfidf_matrix, vocabulary, idf_values, df = load_cached_data(cache_dir)

    # Perform the search
    results = search_query(query, tfidf_matrix, df, vocabulary)

    # Display the results
    for result in results:
        print(f"Filename: {result['filename']}")
        print(f"Similarity Score: {result['similarity']:.4f}")
        print(f"Content Snippet: {result['content'][:200]}")  # Display first 200 characters
        print("-" * 40)
