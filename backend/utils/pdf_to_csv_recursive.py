# File: backend/utils/pdf_to_csv_recursive.py

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
                if page_text:
                    logger.debug(f"Extracted text from page {page_num} of {pdf_path}: {page_text[:100]}...")
                    all_text += page_text + '\n'
                else:
                    logger.warning(f"No text found on page {page_num} of {pdf_path}")
            if all_text.strip():
                logger.info(f"Successfully extracted text from {pdf_path}")
            else:
                logger.warning(f"No extractable text found in {pdf_path}. It might be an image-based PDF.")
            return all_text
    except Exception as e:
        logger.error(f"Error extracting text from {pdf_path}: {e}")
        return ''

def find_pdfs_recursively(directory: str):
    """
    Recursively finds all PDF files in a directory and its subdirectories.

    Args:
        directory (str): The directory to search for PDF files.

    Returns:
        list: A list of full file paths to PDF files.
    """
    pdf_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(".pdf"):
                pdf_files.append(os.path.join(root, file))
    return pdf_files

def pdfs_to_csv(pdf_directory: str, csv_output_path: str) -> None:
    """
    Converts all PDF files in a directory and subdirectories to a CSV file with extracted text.

    Args:
        pdf_directory (str): Directory containing PDF files.
        csv_output_path (str): Path to save the resulting CSV file.
    """
    pdf_files = find_pdfs_recursively(pdf_directory)

    if not pdf_files:
        logger.warning(f"No PDF files found in {pdf_directory}.")
        return

    logger.info(f"Found {len(pdf_files)} PDF files. Starting extraction...")

    data = []
    for pdf_file in pdf_files:
        logger.info(f"Processing {pdf_file}...")
        text = extract_text_from_pdf(pdf_file)
        data.append({'filename': os.path.basename(pdf_file), 'content': text})

    if data:
        df = pd.DataFrame(data)
        df.to_csv(csv_output_path, index=False)
        logger.info(f"PDF data successfully saved to {csv_output_path}")
    else:
        logger.warning("No data to save to CSV. The PDF files might be empty or invalid.")

if __name__ == "__main__":
    pdf_directory = 'precompute-data/download_vlr_pdfs'  # Replace with the path to your PDF directory
    csv_output_path = 'precompute-data/pdfs.csv'  # Replace with the path for the output CSV
    logger.info("Starting PDF to CSV conversion...")
    pdfs_to_csv(pdf_directory, csv_output_path)
    logger.info("PDF to CSV conversion finished.")
