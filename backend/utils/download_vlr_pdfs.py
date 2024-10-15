# File: backend/utils/download_vlr_pdfs.py
# Optimized script to download all PDF files from any URL found on the page, with custom User-Agent
# Handles pagination, saves PDFs into hash-based subdirectories, and logs progress
# Also handles SSL issues related to legacy renegotiation by using an SSLAdapter

import requests
from bs4 import BeautifulSoup
import os
from urllib.parse import urljoin
import logging
import csv
import hashlib
import gc
import re
import ssl
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Define the headers to include the custom User-Agent
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
}

# CSV file to keep a mapping of URLs to downloaded PDF files
CSV_FILE_PATH = 'precompute-data/download_vlr_pdfs/downloaded_pdfs.csv'

# Custom SSLAdapter to handle legacy SSL renegotiation
class SSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.options |= ssl.OP_LEGACY_SERVER_CONNECT  # Enable legacy renegotiation
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

def initialize_csv():
    """Initialize the CSV file if it doesn't exist."""
    if not os.path.exists(CSV_FILE_PATH):
        logging.info(f"Creating CSV file for tracking downloads: {CSV_FILE_PATH}")
        with open(CSV_FILE_PATH, 'w', newline='') as csvfile:
            csvwriter = csv.writer(csvfile)
            csvwriter.writerow(['PDF_URL', 'Local_File_Name'])

def add_to_csv(pdf_url, file_path):
    """Add a mapping of the PDF URL to its local file name in the CSV file."""
    with open(CSV_FILE_PATH, 'a', newline='') as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow([pdf_url, file_path])
    logging.debug(f"Added to CSV: {pdf_url} -> {file_path}")

def generate_hash_subdirectory(pdf_url):
    """Generate a hash-based subdirectory using a hash of the PDF URL."""
    hash_object = hashlib.md5(pdf_url.encode())  # Generate a hash of the URL
    hash_suffix = hash_object.hexdigest()[:8]  # Use the first 8 characters of the hash
    subdirectory = f"precompute-data/download_vlr_pdfs/{hash_suffix}"  # Use the hash as the subdirectory name
    return subdirectory

def create_session_with_ssl_adapter():
    """Create a requests session with the SSLAdapter to handle legacy SSL issues."""
    session = requests.Session()
    adapter = SSLAdapter()
    session.mount('https://', adapter)
    return session

def download_pdfs_from_url(url, visited_urls=None, session=None):
    if visited_urls is None:
        visited_urls = set()

    # Avoid revisiting the same URL
    if url in visited_urls:
        logging.debug(f"Skipping already visited URL: {url}")
        return
    visited_urls.add(url)

    # Use the provided session with SSL adapter
    if session is None:
        session = create_session_with_ssl_adapter()

    # Log the URL being visited
    logging.info(f"Visiting URL: {url}")

    # Get the webpage content with the specified User-Agent, with streaming to reduce memory usage
    logging.debug(f"Equivalent curl command: curl -A \"{HEADERS['User-Agent']}\" {url}")
    try:
        with session.get(url, headers=HEADERS, stream=True) as response:
            response.raise_for_status()  # Check for HTTP errors
            soup = BeautifulSoup(response.content, 'html.parser')
    except requests.exceptions.RequestException as e:
        logging.error(f"Error accessing {url}: {e}")
        return

    # Find and download PDF links from the current page using a regex pattern for .pdf
    for link in soup.find_all('a', href=True):
        href = link['href']
        full_url = urljoin(url, href)

        # Check if the URL ends with .pdf using regex
        if re.search(r"\.pdf$", full_url, re.IGNORECASE):
            logging.debug(f"Found PDF link: {full_url}")
            download_pdf(full_url, session)
        else:
            logging.debug(f"Ignored hyperlink: {full_url} (not a PDF)")

    # Look for pagination links and navigate them
    pagination_links = soup.select('a[href*="page="]')
    for page_link in pagination_links:
        page_url = urljoin(url, page_link['href'])
        if page_url not in visited_urls:
            logging.debug(f"Found pagination link: {page_url}")
            download_pdfs_from_url(page_url, visited_urls, session)

    # Perform garbage collection after each batch
    gc.collect()

def download_pdf(pdf_url, session):
    original_filename = pdf_url.split("/")[-1]
    hash_subdirectory = generate_hash_subdirectory(pdf_url)
    
    # Create the hash-based subdirectory if it doesn't exist
    if not os.path.exists(hash_subdirectory):
        os.makedirs(hash_subdirectory)
        logging.debug(f"Created directory: {hash_subdirectory}")

    file_path = os.path.join(hash_subdirectory, original_filename)
    
    # Check if the file already exists
    if os.path.exists(file_path):
        logging.info(f"PDF already downloaded, skipping: {file_path}")
        return

    logging.info(f"Downloading PDF: {pdf_url} into {file_path}")
    logging.debug(f"Equivalent curl command: curl -A \"{HEADERS['User-Agent']}\" -o {file_path} {pdf_url}")

    # Stream the PDF download to avoid memory overload
    try:
        with session.get(pdf_url, headers=HEADERS, stream=True) as pdf_response:
            pdf_response.raise_for_status()
            with open(file_path, 'wb') as pdf_file:
                for chunk in pdf_response.iter_content(chunk_size=1024):
                    if chunk:  # Filter out keep-alive chunks
                        pdf_file.write(chunk)
        logging.info(f"Successfully downloaded: {file_path}")
        add_to_csv(pdf_url, file_path)  # Add the download to the CSV tracking file
    except Exception as e:
        logging.error(f"Failed to download {pdf_url}. Error: {e}")

    # Uncomment to perform garbage collection after each download
    # gc.collect()

if __name__ == "__main__":
    # List of URLs to scrape
    urls_to_scrape = [
        "https://sdgs.un.org/topics/voluntary-local-reviews",
        "https://unhabitat.org/topics/voluntary-local-reviews?order=field_year_of_publication_vlr&sort=desc#block-vlrworldmap",
        "https://www.local2030.org/vlrs",
        "https://www.iges.or.jp/en/projects/vlr"
    ]

    logging.info(f"Starting PDF download for {len(urls_to_scrape)} websites.")
    
    # Initialize the CSV file
    initialize_csv()

    # Create a session with the custom SSL adapter
    session = create_session_with_ssl_adapter()

    # Process each URL in the list
    for url in urls_to_scrape:
        logging.info(f"Processing URL: {url}")
        download_pdfs_from_url(url, session=session)
    
    logging.info("Finished scraping and downloading PDFs.")
