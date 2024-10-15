# File: backend/utils/pdf_to_csv.py

import os
import pandas as pd
import pdfplumber
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extracts text from a single PDF file using pdfplumber.

    Args:
        pdf_path (str): Path to the PDF file.

    Returns:
        str: Extracted text or an empty string if extraction fails.
    """
    try:
        logger.debug(f"Opening PDF: {pdf_path}")
        with pdfplumber.open(pdf_path) as pdf:
            all_text = ''
            for page_num, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text()
                logger.debug(f"Extracted text from page {page_num} of {pdf_path}: {page_text[:100]}...")  # Log first 100 characters
                all_text += page_text + '\n' if page_text else ''
            if all_text.strip():
                logger.info(f"Successfully extracted text from {pdf_path}")
            else:
                logger.warning(f"No text extracted from {pdf_path}. It might be an image-based PDF.")
            return all_text
    except Exception as e:
        logger.error(f"Error extracting text from {pdf_path}: {e}")
        return ''

def pdfs_to_csv(pdf_directory: str, csv_output_path: str) -> None:
    """
    Converts all PDF files in a directory to a CSV file with extracted text.

    Args:
        pdf_directory (str): Directory containing PDF files.
        csv_output_path (str): Path to save the resulting CSV file.
    """
    data = []

    if not os.path.exists(pdf_directory):
        logger.error(f"PDF directory {pdf_directory} does not exist.")
        return

    pdf_files = [f for f in os.listdir(pdf_directory) if f.endswith(".pdf")]
    if not pdf_files:
        logger.warning(f"No PDF files found in {pdf_directory}.")
        return
    
    logger.info(f"Found {len(pdf_files)} PDF files in {pdf_directory}. Starting extraction process...")

    for filename in pdf_files:
        pdf_path = os.path.join(pdf_directory, filename)
        logger.info(f"Processing {pdf_path}...")
        text = extract_text_from_pdf(pdf_path)
        data.append({'filename': filename, 'content': text})

    if data:
        df = pd.DataFrame(data)
        df.to_csv(csv_output_path, index=False)
        logger.info(f"PDF data successfully saved to {csv_output_path}")
    else:
        logger.warning("No data to save to CSV. The PDF files might be empty or invalid.")

if __name__ == "__main__":
    pdf_directory = 'precompute-data'  # Replace with the path to your PDF directory
    csv_output_path = 'precompute-data/pdfs.csv'  # Replace with the path for the output CSV
    logger.info("Starting PDF to CSV conversion...")
    pdfs_to_csv(pdf_directory, csv_output_path)
    logger.info("PDF to CSV conversion finished.")
