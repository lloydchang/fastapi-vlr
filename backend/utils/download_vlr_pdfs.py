# File: backend/utils/download_vlr_pdfs.py
# Optimized script to download all PDF files from any URL found on the page, with custom User-Agent
# Handles pagination, saves PDFs into hash-based subdirectories, logs progress, skips previously visited URLs,
# and stores the timestamp of the visited URL. Also handles SSL issues using an SSLAdapter.

import requests
from bs4 import BeautifulSoup
import os
from urllib.parse import urljoin, urlparse
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

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
}

CSV_FILE_PATH = 'precompute-data/download_vlr_pdfs/downloaded_pdfs.csv'
VISITED_URLS_CSV_FILE = 'precompute-data/download_vlr_pdfs/visited_urls.csv'

class SSLAdapter(HTTPAdapter):
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
        full_url = urljoin(url, href)  # Properly join relative URLs

        if re.search(r"\.pdf$", full_url, re.IGNORECASE):
            download_pdf(full_url, session)
        elif is_internal_link(full_url, url) and full_url not in visited_urls:
            logging.debug(f"Following internal link: {full_url}")
            download_pdfs_from_url(full_url, visited_urls, session)

    pagination_links = soup.select('a[href*="page="]')
    for page_link in pagination_links:
        page_url = urljoin(url, page_link['href'])
        if page_url not in visited_urls:
            logging.debug(f"Found pagination link: {page_url}")
            download_pdfs_from_url(page_url, visited_urls, session)

    gc.collect()

def is_internal_link(link, base_url):
    """Check if a link belongs to the same domain as the base URL."""
    base_netloc = urlparse(base_url).netloc
    link_netloc = urlparse(link).netloc
    return base_netloc == link_netloc or not link_netloc

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
        "https://www.iges.or.jp/en/projects/vlr",
        "https://www.iges.or.jp/en/vlr/agadir",
        "https://www.iges.or.jp/en/vlr/agios-dimitrios",
        "https://www.iges.or.jp/en/vlr/alor-gajah",
        "https://www.iges.or.jp/en/vlr/amman",
        "https://www.iges.or.jp/en/vlr/asker",
        "https://www.iges.or.jp/en/vlr/atenas",
        "https://www.iges.or.jp/en/vlr/avcilar",
        "https://www.iges.or.jp/en/vlr/bad-kostritz",
        "https://www.iges.or.jp/en/vlr/barcelona",
        "https://www.iges.or.jp/en/vlr/belen",
        "https://www.iges.or.jp/en/vlr/bonn",
        "https://www.iges.or.jp/en/vlr/bristol",
        "https://www.iges.or.jp/en/vlr/buenos-aires",
        "https://www.iges.or.jp/en/vlr/capetown",
        "https://www.iges.or.jp/en/vlr/cascais",
        "https://www.iges.or.jp/en/vlr/cochabamba",
        "https://www.iges.or.jp/en/vlr/cordoba",
        "https://www.iges.or.jp/en/vlr/dangjin",
        "https://www.iges.or.jp/en/vlr/dhulikhel",
        "https://www.iges.or.jp/en/vlr/dusseldorf",
        "https://www.iges.or.jp/en/vlr/el-alto",
        "https://www.iges.or.jp/en/vlr/escazu",
        "https://www.iges.or.jp/en/vlr/espoo",
        "https://www.iges.or.jp/en/vlr/fatih",
        "https://www.iges.or.jp/en/vlr/florence",
        "https://www.iges.or.jp/en/vlr/furstenfeldbruck",
        "https://www.iges.or.jp/en/vlr/ghent",
        "https://www.iges.or.jp/en/vlr/gladsaxe",
        "https://www.iges.or.jp/en/vlr/goicoechea",
        "https://www.iges.or.jp/en/vlr/hamamatsu",
        "https://www.iges.or.jp/en/vlr/hamburg",
        "https://www.iges.or.jp/en/vlr/hawaii",
        "https://www.iges.or.jp/en/vlr/helsinki",
        "https://www.iges.or.jp/en/vlr/hsinchu",
        "https://www.iges.or.jp/en/vlr/jaen",
        "https://www.iges.or.jp/en/vlr/jakarta",
        "https://www.iges.or.jp/en/vlr/jambi",
        "https://www.iges.or.jp/en/vlr/kaohsiung",
        "https://www.iges.or.jp/en/vlr/karatay",
        "https://www.iges.or.jp/en/vlr/kelowna",
        "https://www.iges.or.jp/en/vlr/kiel",
        "https://www.iges.or.jp/en/vlr/kitakyushu",
        "https://www.iges.or.jp/en/vlr/kuala-lumpur",
        "https://www.iges.or.jp/en/vlr/la-paz",
        "https://www.iges.or.jp/en/vlr/liverpool",
        "https://www.iges.or.jp/en/vlr/los_angeles",
        "https://www.iges.or.jp/en/vlr/lviv",
        "https://www.iges.or.jp/en/vlr/madrid",
        "https://www.iges.or.jp/en/vlr/mafra",
        "https://www.iges.or.jp/en/vlr/malmo",
        "https://www.iges.or.jp/en/vlr/manizales",
        "https://www.iges.or.jp/en/vlr/mannheim",
        "https://www.iges.or.jp/en/vlr/melaka",
        "https://www.iges.or.jp/en/vlr/melbourne",
        "https://www.iges.or.jp/en/vlr/merida",
        "https://www.iges.or.jp/en/vlr/montevideo",
        "https://www.iges.or.jp/en/vlr/new-taipei",
        "https://www.iges.or.jp/en/vlr/newyork",
        "https://www.iges.or.jp/en/vlr/niteroi",
        "https://www.iges.or.jp/en/vlr/nst",
        "https://www.iges.or.jp/en/vlr/oaxaca",
        "https://www.iges.or.jp/en/vlr/orlando",
        "https://www.iges.or.jp/en/vlr/pingtung-county",
        "https://www.iges.or.jp/en/vlr/pittsburgh",
        "https://www.iges.or.jp/en/vlr/puriscal",
        "https://www.iges.or.jp/en/vlr/rio-de-janeiro",
        "https://www.iges.or.jp/en/vlr/rottenburg-am-neckar",
        "https://www.iges.or.jp/en/vlr/sado",
        "https://www.iges.or.jp/en/vlr/santa-cruz",
        "https://www.iges.or.jp/en/vlr/santana_de_parnaiba",
        "https://www.iges.or.jp/en/vlr/sarchi",
        "https://www.iges.or.jp/en/vlr/seodaemun",
        "https://www.iges.or.jp/en/vlr/sepang",
        "https://www.iges.or.jp/en/vlr/shah-alam",
        "https://www.iges.or.jp/en/vlr/shimokawa",
        "https://www.iges.or.jp/en/vlr/shinan-gun",
        "https://www.iges.or.jp/en/vlr/singra",
        "https://www.iges.or.jp/en/vlr/skiathos",
        "https://www.iges.or.jp/en/vlr/stuttgart",
        "https://www.iges.or.jp/en/vlr/subang-jaya",
        "https://www.iges.or.jp/en/vlr/sultanbeyli",
        "https://www.iges.or.jp/en/vlr/suwon",
        "https://www.iges.or.jp/en/vlr/taichung",
        "https://www.iges.or.jp/en/vlr/tainan",
        "https://www.iges.or.jp/en/vlr/taipei",
        "https://www.iges.or.jp/en/vlr/tampere",
        "https://www.iges.or.jp/en/vlr/taoyuan",
        "https://www.iges.or.jp/en/vlr/tokyo",
        "https://www.iges.or.jp/en/vlr/toyama,"
        "https://www.iges.or.jp/en/vlr/toyota",
        "https://www.iges.or.jp/en/vlr/turku",
        "https://www.iges.or.jp/en/vlr/vantaa",
        "https://www.iges.or.jp/en/vlr/west-java",
        "https://www.iges.or.jp/en/vlr/winnipeg",
        "https://www.iges.or.jp/en/vlr/yokohama",
        "https://www.iges.or.jp/en/vlr/yunlin",
    ]

    logging.info(f"Starting PDF download for {len(urls_to_scrape)} websites.")
    initialize_csv(CSV_FILE_PATH, ['PDF_URL', 'Local_File_Name'])
    initialize_csv(VISITED_URLS_CSV_FILE, ['Visited_URL', 'Timestamp'])

    visited_urls = load_visited_urls()
    session = create_session_with_ssl_adapter()

    for url in urls_to_scrape:
        download_pdfs_from_url(url, visited_urls, session)

    logging.info("Finished scraping and downloading PDFs.")
