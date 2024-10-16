# File: backend/utils/download_vlr_pdfs.py
# Optimized script to download all PDF files from any URL found on the page, with custom User-Agent
# Handles pagination, saves PDFs into hash-based subdirectories, logs progress, skips previously visited URLs,
# and stores the timestamp of the visited URL. Also handles SSL issues using an SSLAdapter.

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
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
from selenium import webdriver  # Import selenium
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Headers for requests to simulate a browser user-agent
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
}

CSV_FILE_PATH = 'precompute-data/download_vlr_pdfs/downloaded_pdfs.csv'
VISITED_URLS_CSV_FILE = 'precompute-data/download_vlr_pdfs/visited_urls.csv'

class SSLAdapter(HTTPAdapter):
    """Custom SSLAdapter to handle legacy SSL renegotiation."""
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.options |= ssl.OP_LEGACY_SERVER_CONNECT
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

def initialize_csv(file_path, headers):
    if not os.path.exists(file_path):
        logging.info(f"Creating CSV file: {file_path}")
        with open(file_path, 'w', newline='') as csvfile:
            csv.writer(csvfile).writerow(headers)

def load_visited_urls():
    if not os.path.exists(VISITED_URLS_CSV_FILE):
        return set()
    with open(VISITED_URLS_CSV_FILE, 'r') as csvfile:
        return {row[0] for row in csv.reader(csvfile) if row}

def add_to_visited_urls(url):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(VISITED_URLS_CSV_FILE, 'a', newline='') as csvfile:
        csv.writer(csvfile).writerow([url, timestamp])
    logging.debug(f"Added to visited URLs: {url} at {timestamp}")

def add_to_csv(pdf_url, file_path):
    with open(CSV_FILE_PATH, 'a', newline='') as csvfile:
        csv.writer(csvfile).writerow([pdf_url, file_path])
    logging.debug(f"Added to CSV: {pdf_url} -> {file_path}")

def generate_hash_subdirectory(pdf_url):
    hash_suffix = hashlib.md5(pdf_url.encode()).hexdigest()[:8]
    subdirectory = f"precompute-data/download_vlr_pdfs/{hash_suffix}"
    os.makedirs(subdirectory, exist_ok=True)
    return subdirectory

def create_session_with_ssl_adapter():
    session = requests.Session()
    session.mount('https://', SSLAdapter())
    return session

def use_selenium(url):
    """Use Selenium to fetch the webpage if regular requests fail."""
    logging.info(f"Attempting with Selenium for URL: {url}")
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
        driver.get(url)
        driver.implicitly_wait(10)
        page_source = driver.page_source
        driver.quit()
        return BeautifulSoup(page_source, 'html.parser')
    except Exception as e:
        logging.error(f"Selenium failed for {url}: {e}")
        return None

def download_pdfs_from_url(url, visited_urls=None, session=None):
    if visited_urls is None:
        visited_urls = set()

    if url in visited_urls:
        logging.debug(f"Skipping already visited URL: {url}")
        return
    visited_urls.add(url)

    if session is None:
        session = create_session_with_ssl_adapter()

    logging.info(f"Visiting URL: {url}")
    try:
        with session.get(url, headers=HEADERS, stream=True) as response:
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

    add_to_visited_urls(url)

    for link in soup.find_all('a', href=True):
        href = link['href']
        full_url = urljoin(url, href)

        if re.search(r"\.pdf$", full_url, re.IGNORECASE):
            download_pdf(full_url, session)
        elif full_url.startswith(url) and full_url not in visited_urls:
            logging.debug(f"Following internal link: {full_url}")
            download_pdfs_from_url(full_url, visited_urls, session)

    pagination_links = soup.select('a[href*="page="]')
    for page_link in pagination_links:
        page_url = urljoin(url, page_link['href'])
        if page_url not in visited_urls:
            logging.debug(f"Found pagination link: {page_url}")
            download_pdfs_from_url(page_url, visited_urls, session)

    gc.collect()

def download_pdf(pdf_url, session):
    original_filename = pdf_url.split("/")[-1]
    subdirectory = generate_hash_subdirectory(pdf_url)
    file_path = os.path.join(subdirectory, original_filename)

    if os.path.exists(file_path):
        logging.info(f"PDF already downloaded, skipping: {file_path}")
        return

    logging.info(f"Downloading PDF: {pdf_url} into {file_path}")
    try:
        with session.get(pdf_url, headers=HEADERS, stream=True) as pdf_response:
            pdf_response.raise_for_status()
            with open(file_path, 'wb') as pdf_file:
                for chunk in pdf_response.iter_content(1024):
                    if chunk:
                        pdf_file.write(chunk)
        add_to_csv(pdf_url, file_path)
    except Exception as e:
        logging.error(f"Failed to download {pdf_url}. Error: {e}")

if __name__ == "__main__":
    urls_to_scrape = [
        "https://sdgs.un.org/topics/voluntary-local-reviews",
        "https://unhabitat.org/topics/voluntary-local-reviews?order=field_year_of_publication_vlr&sort=desc#block-vlrworldmap",
        "https://www.local2030.org/vlrs",
        "https://www.iges.or.jp/en/projects/vlr"
    ]

    logging.info(f"Starting PDF download for {len(urls_to_scrape)} websites.")
    initialize_csv(CSV_FILE_PATH, ['PDF_URL', 'Local_File_Name'])
    initialize_csv(VISITED_URLS_CSV_FILE, ['Visited_URL', 'Timestamp'])

    visited_urls = load_visited_urls()
    session = create_session_with_ssl_adapter()

    for url in urls_to_scrape:
        download_pdfs_from_url(url, visited_urls, session)

    logging.info("Finished scraping and downloading PDFs.")
