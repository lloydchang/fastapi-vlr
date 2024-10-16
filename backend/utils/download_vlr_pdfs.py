# File: fastapi-vlr/backend/utils/download_vlr_pdfs.py

import requests
from bs4 import BeautifulSoup
import os
import logging
import csv
import hashlib
import ssl
from datetime import datetime
from urllib.parse import urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import re
from tqdm import tqdm
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("download_vlr_pdfs.log"),
        logging.StreamHandler()
    ]
)

# Constants
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'
                  ' Chrome/129.0.0.0 Safari/537.36'
}
BASE_SCRIPT_DIR = 'precompute-data/download_vlr_pdfs'
BASE_DOWNLOAD_DIR = 'precompute-data/download_vlr_pdfs/downloads'
CSV_FILE_PATH = os.path.join(BASE_SCRIPT_DIR, 'downloaded_pdfs.csv')
VISITED_URLS_CSV_FILE = os.path.join(BASE_SCRIPT_DIR, 'visited_urls.csv')
UNIQUE_PDFS_CSV_FILE = os.path.join(BASE_SCRIPT_DIR, 'unique_pdfs.csv')
DUPLICATE_PDFS_CSV_FILE = os.path.join(BASE_SCRIPT_DIR, 'duplicate_pdfs.csv')
URLS_FILE_PATH = os.path.join(BASE_SCRIPT_DIR, 'urls.txt')  # External file containing all URLs, one per line

# Ensure base download directory exists
os.makedirs(BASE_DOWNLOAD_DIR, exist_ok=True)

def initialize_csv(file_path, headers):
    """Create a CSV file with headers if it doesn't exist."""
    if not os.path.exists(file_path):
        logging.info(f"Creating CSV file: {file_path}")
        with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(headers)

def load_csv_to_set(file_path, column_index=0):
    """Load a specific column from a CSV file into a set."""
    if not os.path.exists(file_path) or os.stat(file_path).st_size == 0:
        logging.warning(f"{file_path} is missing or empty.")
        return set()
    
    loaded_set = set()
    with open(file_path, 'r', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        next(reader, None)  # Skip header
        for row in reader:
            if len(row) > column_index:
                loaded_set.add(row[column_index])
    return loaded_set

def add_to_csv(file_path, row):
    """Add a new row to a CSV file."""
    with open(file_path, 'a', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(row)
    logging.debug(f"Added row to {file_path}: {row}")

def generate_hash_from_response(response):
    """Generate a SHA256 hash from the response content."""
    sha256 = hashlib.sha256()
    try:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                sha256.update(chunk)
    except Exception as e:
        logging.error(f"Error generating hash from response: {e}")
        return None
    return sha256.hexdigest()

class SSLAdapterWithRetries(HTTPAdapter):
    """An HTTPS adapter that uses a custom SSL context and retry strategy."""
    def __init__(self, max_retries=3, *args, **kwargs):
        self.max_retries = max_retries
        super().__init__(max_retries=self.max_retries, *args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.options |= ssl.OP_LEGACY_SERVER_CONNECT  # Retain this if needed
        kwargs['ssl_context'] = context
        super().init_poolmanager(*args, **kwargs)

def create_session_with_ssl_adapter():
    """Create an HTTP session with SSL support and retry strategy."""
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]  # Updated from method_whitelist
    )
    adapter = SSLAdapterWithRetries(max_retries=retries)
    session.mount('https://', adapter)
    session.headers.update(HEADERS)
    return session

def use_selenium(url):
    """Use Selenium to load the webpage when access is restricted."""
    logging.info(f"Attempting with Selenium for URL: {url}")
    try:
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.get(url)
        driver.implicitly_wait(10)
        page_source = driver.page_source
        driver.quit()
        return BeautifulSoup(page_source, 'html.parser')
    except Exception as e:
        logging.error(f"Selenium failed for {url}: {e}")
        return None

def is_pdf_url(url):
    """Check if the URL points directly to a PDF."""
    return url.lower().endswith('.pdf')

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10),
       retry=retry_if_exception_type(requests.exceptions.RequestException))
def download_pdfs_from_url(url, visited_urls, unique_hashes, session):
    """Scrape the page and download PDFs."""
    if url in visited_urls:
        logging.debug(f"Skipping already visited URL: {url}")
        return

    logging.info(f"Processing URL: {url}")
    visited_urls.add(url)
    add_to_csv(VISITED_URLS_CSV_FILE, [url, datetime.now().strftime('%Y-%m-%d %H:%M:%S')])

    if is_pdf_url(url):
        # Direct PDF link
        process_pdf(url, session, unique_hashes)
        return

    try:
        response = session.get(url, timeout=30)
        if response.status_code == 403:
            logging.warning(f"403 Forbidden for {url}. Using Selenium.")
            soup = use_selenium(url)
        else:
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
    except requests.exceptions.RequestException as e:
        logging.error(f"Error accessing {url}: {e}")
        return

    if not soup:
        return

    # Find all PDF links in the page
    for link in soup.find_all('a', href=True):
        href = link['href']
        full_url = urljoin(url, href)

        if is_pdf_url(full_url):
            process_pdf(full_url, session, unique_hashes)

def process_pdf(pdf_url, session, unique_hashes):
    """Download PDF and track duplicates using content hash."""
    try:
        with session.get(pdf_url, stream=True, timeout=60) as response:
            response.raise_for_status()

            # Check if response is a PDF
            content_type = response.headers.get('Content-Type', '').lower()
            if 'application/pdf' not in content_type:
                logging.warning(f"URL does not point to a PDF: {pdf_url}")
                return

            # Generate hash on-the-fly
            pdf_hash = generate_hash_from_response(response)
            if not pdf_hash:
                logging.error(f"Failed to generate hash for {pdf_url}")
                return

            if pdf_hash in unique_hashes:
                logging.info(f"Duplicate PDF detected: {pdf_url}")
                add_to_csv(DUPLICATE_PDFS_CSV_FILE, [pdf_url, '', pdf_hash])
                return

            # Reset the response for downloading
            response = session.get(pdf_url, stream=True, timeout=60)
            response.raise_for_status()

            original_filename = os.path.basename(pdf_url)
            if not original_filename.lower().endswith('.pdf'):
                original_filename += '.pdf'

            # Define subdirectory based on hash
            hash_suffix = pdf_hash[:8]
            subdirectory = os.path.join(BASE_DOWNLOAD_DIR, hash_suffix)
            os.makedirs(subdirectory, exist_ok=True)
            final_file_path = os.path.join(subdirectory, original_filename)

            # Handle filename conflicts
            base, ext = os.path.splitext(original_filename)
            counter = 1
            while os.path.exists(final_file_path):
                final_file_path = os.path.join(subdirectory, f"{base}_{counter}{ext}")
                counter += 1

            # Download and save the PDF
            with open(final_file_path, 'wb') as pdf_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        pdf_file.write(chunk)

            logging.info(f"Successfully downloaded: {final_file_path}")

            # Update CSV and hash set
            add_to_csv(UNIQUE_PDFS_CSV_FILE, [pdf_url, final_file_path, pdf_hash])
            add_to_csv(CSV_FILE_PATH, [pdf_url, final_file_path])
            unique_hashes.add(pdf_hash)

    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to download {pdf_url}. Error: {e}")
    except Exception as e:
        logging.error(f"Unexpected error while downloading {pdf_url}: {e}")

def load_urls(file_path):
    """Load URLs from an external text file."""
    if not os.path.exists(file_path):
        logging.error(f"URLs file not found: {file_path}")
        return []
    with open(file_path, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip()]
    return urls

def main():
    """Main function to orchestrate PDF downloads."""
    # Initialize CSV files with headers
    initialize_csv(CSV_FILE_PATH, ['PDF_URL', 'Local_File_Path'])
    initialize_csv(VISITED_URLS_CSV_FILE, ['Visited_URL', 'Timestamp'])
    initialize_csv(UNIQUE_PDFS_CSV_FILE, ['PDF_URL', 'Local_File_Path', 'Hash'])
    initialize_csv(DUPLICATE_PDFS_CSV_FILE, ['PDF_URL', 'Local_File_Path', 'Hash'])

    # Load already visited URLs and unique PDF hashes
    visited_urls = load_csv_to_set(VISITED_URLS_CSV_FILE, column_index=0)
    unique_hashes = load_csv_to_set(UNIQUE_PDFS_CSV_FILE, column_index=2)

    session = create_session_with_ssl_adapter()

    # Load URLs from external file
    urls_to_scrape = load_urls(URLS_FILE_PATH)
    if not urls_to_scrape:
        logging.error("No URLs to scrape. Exiting.")
        return

    # Use tqdm for progress bar
    for url in tqdm(urls_to_scrape, desc="Downloading PDFs"):
        download_pdfs_from_url(url, visited_urls, unique_hashes, session)

    logging.info("Finished scraping and downloading PDFs.")

if __name__ == "__main__":
    main()
