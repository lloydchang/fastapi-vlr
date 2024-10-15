# File: backend/utils/process_csv.py

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from scipy.sparse import save_npz
import os
import numpy as np
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def process_csv(csv_file_path: str, cache_dir: str):
    """
    Processes the CSV file to extract text content and create a TF-IDF matrix.

    Args:
        csv_file_path (str): Path to the CSV file containing PDF content.
        cache_dir (str): Directory to save the processed cache files.
    """
    logger.info(f"Starting to process CSV file: {csv_file_path}")

    # Load the CSV
    if not os.path.exists(csv_file_path):
        logger.error(f"CSV file {csv_file_path} does not exist.")
        return
    
    try:
        df = pd.read_csv(csv_file_path)
        logger.debug(f"Loaded CSV file with {df.shape[0]} rows and {df.shape[1]} columns.")
    except Exception as e:
        logger.error(f"Failed to read CSV file {csv_file_path}: {e}")
        return

    # Check if 'content' column exists
    if 'content' not in df.columns:
        logger.error(f"Expected 'content' column not found in {csv_file_path}")
        return

    # Prepare the text for TF-IDF vectorization
    texts = df['content'].fillna('').tolist()
    logger.info(f"Preparing {len(texts)} documents for TF-IDF vectorization.")

    try:
        # Create TF-IDF matrix
        vectorizer = TfidfVectorizer(stop_words='english', max_features=10000)
        tfidf_matrix = vectorizer.fit_transform(texts)
        logger.info(f"TF-IDF matrix created with shape {tfidf_matrix.shape}.")
    except Exception as e:
        logger.error(f"Error creating TF-IDF matrix: {e}")
        return

    # Save the sparse matrix and vectorizer components to the cache directory
    os.makedirs(cache_dir, exist_ok=True)
    logger.debug(f"Ensured that cache directory {cache_dir} exists.")

    try:
        save_npz(os.path.join(cache_dir, "tfidf_matrix.npz"), tfidf_matrix)
        logger.info(f"TF-IDF matrix saved to {os.path.join(cache_dir, 'tfidf_matrix.npz')}.")
    except Exception as e:
        logger.error(f"Error saving TF-IDF matrix: {e}")
        return

    # Save vocabulary and IDF values
    tfidf_metadata_path = os.path.join(cache_dir, "tfidf_metadata.npz")
    try:
        np.savez_compressed(tfidf_metadata_path, vocabulary=vectorizer.vocabulary_, idf_values=vectorizer.idf_)
        logger.info(f"TF-IDF metadata saved to {tfidf_metadata_path}.")
    except Exception as e:
        logger.error(f"Error saving TF-IDF metadata: {e}")
        return

    logger.info(f"Processed data saved successfully to {cache_dir}")

if __name__ == "__main__":
    csv_file_path = 'precompute-data/pdfs.csv'  # Replace with the path to the converted CSV
    cache_dir = 'backend/fastapi/cache'  # Replace with the directory to store processed cache
    logger.info("Starting CSV processing...")
    process_csv(csv_file_path, cache_dir)
    logger.info("CSV processing completed.")
