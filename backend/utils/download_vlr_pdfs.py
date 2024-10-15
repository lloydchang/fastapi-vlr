# File: backend/utils/download_vlr_pdfs.py
# Script to download all PDF files from specific subdirectories of URLs, recursively traversing links with a custom User-Agent
# Downloads PDFs into a subdirectory called 'precompute-data' and skips already downloaded PDFs
# Keeps a CSV file that maps PDF URLs to local file names and provides detailed debug logging

import requests
from bs4 import BeautifulSoup
import os
from urllib.parse import urljoin, urlparse
import logging
import csv

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Define the headers to include the custom User-Agent
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
}

# CSV file to keep a mapping of URLs to downloaded PDF files
CSV_FILE_PATH = 'precompute-data/downloaded_pdfs.csv'

def initialize_csv():
    """Initialize the CSV file if it doesn't exist."""
    if not os.path.exists(CSV_FILE_PATH):
        logging.info(f"Creating CSV file for tracking downloads: {CSV_FILE_PATH}")
        with open(CSV_FILE_PATH, 'w', newline='') as csvfile:
            csvwriter = csv.writer(csvfile)
            csvwriter.writerow(['PDF_URL', 'Local_File_Name'])

def add_to_csv(pdf_url, file_name):
    """Add a mapping of the PDF URL to its local file name in the CSV file."""
    with open(CSV_FILE_PATH, 'a', newline='') as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow([pdf_url, file_name])
    logging.debug(f"Added to CSV: {pdf_url} -> {file_name}")

def download_pdfs_from_url(url, save_directory="precompute-data", visited_urls=None):
    if visited_urls is None:
        visited_urls = set()

    # Avoid revisiting the same URL
    if url in visited_urls:
        logging.debug(f"Skipping already visited URL: {url}")
        return
    visited_urls.add(url)

    # Define the specific directories for each site
    site_specific_directories = {
        "https://sdgs.un.org": "https://sdgs.un.org/sites/default/files/vlrs/",
        "https://unhabitat.org": "https://unhabitat.org/sites/default/files/",
        "https://www.local2030.org": "https://www.local2030.org/pdf/vlr",
        "https://www.iges.or.jp": "https://www.iges.or.jp/sites/default/files/"
    }

    # Create a directory to save PDFs
    if not os.path.exists(save_directory):
        os.makedirs(save_directory)
        logging.debug(f"Created directory for PDFs: {save_directory}")

    # Get the base domain to apply the correct PDF directory
    base_domain = "{0.scheme}://{0.netloc}".format(urlparse(url))
    specific_directory = site_specific_directories.get(base_domain, None)
    if not specific_directory:
        logging.error(f"No matching directory found for base domain: {base_domain}")
        return

    # Get the webpage content with the specified User-Agent
    logging.info(f"Fetching content from URL: {url}")
    logging.debug(f"Equivalent curl command: curl -A \"{HEADERS['User-Agent']}\" {url}")
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()  # Check for HTTP errors
    except requests.exceptions.RequestException as e:
        logging.error(f"Error accessing {url}: {e}")
        return

    # Parse the webpage content
    soup = BeautifulSoup(response.content, 'html.parser')

    # Find and download PDF links from the current page
    for link in soup.find_all('a', href=True):
        href = link['href']
        full_url = urljoin(url, href)

        # Check if the link is a PDF file in the correct subdirectory
        if full_url.startswith(specific_directory) and full_url.endswith('.pdf'):
            logging.debug(f"Found PDF link: {full_url}")
            download_pdf(full_url, save_directory)
        else:
            logging.debug(f"Ignored hyperlink: {full_url} (not in specific subdirectory)")

def download_pdf(pdf_url, save_directory):
    file_name = os.path.join(save_directory, pdf_url.split("/")[-1])
    
    # Check if the file already exists
    if os.path.exists(file_name):
        logging.info(f"PDF already downloaded, skipping: {file_name}")
        return

    logging.info(f"Downloading PDF: {pdf_url} into {file_name}")
    logging.debug(f"Equivalent curl command: curl -A \"{HEADERS['User-Agent']}\" -o {file_name} {pdf_url}")

    # Download the PDF file with the specified User-Agent
    try:
        with requests.get(pdf_url, headers=HEADERS, stream=True) as pdf_response:
            pdf_response.raise_for_status()
            with open(file_name, 'wb') as pdf_file:
                for chunk in pdf_response.iter_content(chunk_size=8192):
                    if chunk:  # Filter out keep-alive chunks
                        pdf_file.write(chunk)
        logging.info(f"Successfully downloaded: {file_name}")
        add_to_csv(pdf_url, file_name)  # Add the download to the CSV tracking file
    except Exception as e:
        logging.error(f"Failed to download {pdf_url}. Error: {e}")

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

    # Process each URL in the list
    for url in urls_to_scrape:
        logging.info(f"Processing URL: {url}")
        download_pdfs_from_url(url)
    
    logging.info("Finished scraping and downloading PDFs.")
