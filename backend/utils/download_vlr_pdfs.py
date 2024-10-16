# File: backend/utils/download_vlr_pdfs.py
# Optimized script to download all PDF files from any URL found on the page, with custom User-Agent
# Handles pagination, saves PDFs into hash-based subdirectories, logs progress, skips previously visited URLs, and stores the timestamp of the visited URL
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
import cloudscraper  # Import cloudscraper
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
from selenium import webdriver  # Import selenium
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Define the headers to include the custom User-Agent
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
}

# CSV file to keep a mapping of URLs to downloaded PDF files
CSV_FILE_PATH = 'precompute-data/download_vlr_pdfs/downloaded_pdfs.csv'
# CSV file to store the list of visited URLs with timestamps
VISITED_URLS_CSV_FILE = 'precompute-data/download_vlr_pdfs/visited_urls.csv'

# Custom SSLAdapter to handle legacy SSL renegotiation
class SSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.options |= ssl.OP_LEGACY_SERVER_CONNECT  # Enable legacy renegotiation
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

def initialize_csv(file_path, headers):
    """Initialize the CSV file if it doesn't exist."""
    if not os.path.exists(file_path):
        logging.info(f"Creating CSV file: {file_path}")
        with open(file_path, 'w', newline='') as csvfile:
            csvwriter = csv.writer(csvfile)
            csvwriter.writerow(headers)

def load_visited_urls():
    """Load visited URLs from the CSV file."""
    if not os.path.exists(VISITED_URLS_CSV_FILE):
        return set()
    with open(VISITED_URLS_CSV_FILE, 'r') as csvfile:
        csvreader = csv.reader(csvfile)
        return set(row[0] for row in csvreader if row)

def add_to_visited_urls(url):
    """Add a URL and timestamp to the visited URLs CSV."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Get the current date and time
    with open(VISITED_URLS_CSV_FILE, 'a', newline='') as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow([url, timestamp])  # Add the URL and the timestamp
    logging.debug(f"Added to visited URLs: {url} at {timestamp}")

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

def use_cloudscraper_if_needed(url):
    """Fallback to cloudscraper if normal request gets blocked with HTTP 403."""
    logging.info(f"Attempting with cloudscraper for URL: {url}")
    scraper = cloudscraper.create_scraper()
    try:
        response = scraper.get(url)
        response.raise_for_status()  # Check for HTTP errors
        logging.info(f"Successfully accessed {url} using cloudscraper.")
        return BeautifulSoup(response.content, 'html.parser')
    except requests.exceptions.RequestException as e:
        logging.error(f"Cloudscraper also failed for {url}: {e}")
        return None

def use_selenium_if_needed(url):
    """Fallback to Selenium if cloudscraper fails to bypass protections."""
    logging.info(f"Attempting with Selenium for URL: {url}")
    # Start a browser session with Selenium
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
        driver.get(url)
        driver.implicitly_wait(10)  # Wait for page load
        page_source = driver.page_source
        driver.quit()
        logging.info(f"Successfully accessed {url} using Selenium.")
        return BeautifulSoup(page_source, 'html.parser')
    except Exception as e:
        logging.error(f"Selenium failed for {url}: {e}")
        return None

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

    while url:
        # Log the URL being visited
        logging.info(f"Visiting URL: {url}")

        # Get the webpage content with the specified User-Agent, with streaming to reduce memory usage
        logging.debug(f"Equivalent curl command: curl -A \"{HEADERS['User-Agent']}\" {url}")
        try:
            with session.get(url, headers=HEADERS, stream=True) as response:
                if response.status_code == 403:
                    # Handle 403 Forbidden by switching to cloudscraper
                    logging.warning(f"HTTP 403 Forbidden encountered for {url}. Switching to cloudscraper.")
                    soup = use_cloudscraper_if_needed(url)
                    if soup is None:
                        logging.warning(f"Cloudscraper failed for {url}. Switching to Selenium.")
                        soup = use_selenium_if_needed(url)
                else:
                    response.raise_for_status()  # Check for HTTP errors
                    soup = BeautifulSoup(response.content, 'html.parser')
        except requests.exceptions.RequestException as e:
            logging.error(f"Error accessing {url}: {e}")
            return

        # If soup is None, the page couldn't be accessed, so return
        if soup is None:
            return

        # Add this URL to the visited URLs CSV with timestamp
        add_to_visited_urls(url)

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

        # Find pagination links
        pagination_links = soup.select('a[href*="page="]')
        next_url = None
        for page_link in pagination_links:
            next_url_candidate = urljoin(url, page_link['href'])
            if next_url_candidate not in visited_urls:
                next_url = next_url_candidate
                break

        if next_url:
            logging.debug(f"Found pagination link: {next_url}")
            url = next_url  # Set the next page URL for the next iteration
        else:
            logging.debug(f"No more pagination links found.")
            url = None  # No more pagination links, stop the loop

    # Perform garbage collection after processing the URL and pagination
    gc.collect()
