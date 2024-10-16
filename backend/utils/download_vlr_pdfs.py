# File: download_vlr_pdfs.py


# Optimized script to download PDFs in their original format, ensuring uniqueness using content hashing.
# Duplicates are logged instead of deleted, with tracking in `duplicate_pdfs.csv`.

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
from urllib3.poolmanager import PoolManager
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import re

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
BASE_DOWNLOAD_DIR = 'precompute-data/download_vlr_pdfs'
CSV_FILE_PATH = os.path.join(BASE_DOWNLOAD_DIR, 'downloaded_pdfs.csv')
VISITED_URLS_CSV_FILE = os.path.join(BASE_DOWNLOAD_DIR, 'visited_urls.csv')
UNIQUE_PDFS_CSV_FILE = os.path.join(BASE_DOWNLOAD_DIR, 'unique_pdfs.csv')
DUPLICATE_PDFS_CSV_FILE = os.path.join(BASE_DOWNLOAD_DIR, 'duplicate_pdfs.csv')

# Ensure base download directory exists
os.makedirs(BASE_DOWNLOAD_DIR, exist_ok=True)

class SSLAdapter(HTTPAdapter):
    """An HTTPS adapter that uses an arbitrary SSL version."""
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.options |= ssl.OP_LEGACY_SERVER_CONNECT
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

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

def generate_hash(file_path):
    """Generate an MD5 hash of the file content."""
    hasher = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
    except Exception as e:
        logging.error(f"Error generating hash for {file_path}: {e}")
        return None
    return hasher.hexdigest()

def download_pdf(pdf_url, session, unique_hashes):
    """Download PDF and track duplicates using content hash."""
    try:
        response = session.get(pdf_url, headers=HEADERS, stream=True, timeout=30)
        response.raise_for_status()
        
        # Check if response is a PDF
        content_type = response.headers.get('Content-Type', '').lower()
        if 'application/pdf' not in content_type:
            logging.warning(f"URL does not point to a PDF: {pdf_url}")
            return
        
        original_filename = pdf_url.split("/")[-1]
        if not original_filename.lower().endswith('.pdf'):
            original_filename += '.pdf'
        
        # Generate a temporary file path
        temp_dir = os.path.join(BASE_DOWNLOAD_DIR, 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        temp_file_path = os.path.join(temp_dir, original_filename)
        
        # Download the PDF in chunks
        with open(temp_file_path, 'wb') as pdf_file:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    pdf_file.write(chunk)
        
        # Generate hash of downloaded PDF
        pdf_hash = generate_hash(temp_file_path)
        if not pdf_hash:
            logging.error(f"Failed to generate hash for {pdf_url}")
            os.remove(temp_file_path)
            return
        
        if pdf_hash in unique_hashes:
            logging.info(f"Duplicate PDF detected: {pdf_url}")
            add_to_csv(DUPLICATE_PDFS_CSV_FILE, [pdf_url, original_filename, pdf_hash])
            os.remove(temp_file_path)
        else:
            # Move the file to its final destination
            hash_suffix = pdf_hash[:8]
            subdirectory = os.path.join(BASE_DOWNLOAD_DIR, hash_suffix)
            os.makedirs(subdirectory, exist_ok=True)
            final_file_path = os.path.join(subdirectory, original_filename)
            
            # Handle filename conflicts
            if os.path.exists(final_file_path):
                base, ext = os.path.splitext(original_filename)
                counter = 1
                while os.path.exists(final_file_path):
                    final_file_path = os.path.join(subdirectory, f"{base}_{counter}{ext}")
                    counter += 1
            
            os.rename(temp_file_path, final_file_path)
            logging.info(f"Successfully downloaded: {final_file_path}")
            
            # Update CSV and hash set
            add_to_csv(UNIQUE_PDFS_CSV_FILE, [pdf_url, final_file_path, pdf_hash])
            add_to_csv(CSV_FILE_PATH, [pdf_url, final_file_path])
            unique_hashes.add(pdf_hash)
    
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to download {pdf_url}. Error: {e}")
    except Exception as e:
        logging.error(f"Unexpected error while downloading {pdf_url}: {e}")

def generate_hash_subdirectory(pdf_url):
    """Generate a hash-based subdirectory for organizing PDFs."""
    hash_suffix = hashlib.md5(pdf_url.encode()).hexdigest()[:8]
    subdirectory = os.path.join(BASE_DOWNLOAD_DIR, hash_suffix)
    os.makedirs(subdirectory, exist_ok=True)
    return subdirectory

def create_session_with_ssl_adapter():
    """Create an HTTP session with SSL support."""
    session = requests.Session()
    session.mount('https://', SSLAdapter())
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

def download_pdfs_from_url(url, visited_urls, session, unique_hashes):
    """Scrape the page and download PDFs."""
    if url in visited_urls:
        logging.debug(f"Skipping already visited URL: {url}")
        return

    logging.info(f"Processing URL: {url}")
    visited_urls.add(url)
    add_to_csv(VISITED_URLS_CSV_FILE, [url, datetime.now().strftime('%Y-%m-%d %H:%M:%S')])

    if is_pdf_url(url):
        # Direct PDF link
        download_pdf(url, session, unique_hashes)
        return

    try:
        response = session.get(url, headers=HEADERS, timeout=30)
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
            download_pdf(full_url, session, unique_hashes)

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

    # List of URLs to scrape
    urls_to_scrape = [
        # Insert all the URLs you provided here
        "https://hlpf.un.org/sites/default/files/vnrs/2021/10560NVR%20%28Morocco%29.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/10738egypt.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/10756Full%20report%20Mexico%20-%20HLPF%202016%20FINAL.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/15721Belgium_Rev.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/15766Portugal2017_EN_REV_FINAL_29_06_2017.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/15806Brazil_English.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/15881Malaysia.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/16445JapanVNR2017.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/20122VOLUNTARY_NATIONAL_REPORT_060718.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/20269EGY_VNR_2018_final_with_Hyperlink_9720185b45d.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/23429VNR_Report_Tanzania_2019_FINAL.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/26295VNR_2020_Ukraine_Report.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/26314VNR_2020_Mozambique_Report.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/26406VNR_2020_Morocco_Report_French.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/279512021_VNR_Report_Egypt.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/288982021_VNR_Report_Mexico.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/28957210714_VNR_2021_Japan.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2023/Portugal_VNR_Report.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/20531Suwon_Implementation_Report_on_Goal_11_for_HLPF_2018_Final.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/25023VLR_City_of_Mannheim_final.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/AGENDA_EBC2030.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/BRISTOL%20AND%20THE%20SDGs.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/En-route-vers-2030-Rapport-de-mise-en-uvre-en-Wallonie-des-Objectifs-de-dveloppement-durable.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/English_Report%20of%20Localization%20of%20the%20Sustainable%20Development%20Goals.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/Green-Environmental-Sustainability-Progress-Report.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/International-Affairs-VLR-2019.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/LA%27s_Voluntary_Local_Review_of_SDGs_2019.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/Location-of-the-Agenda-2030-in-Barcarena.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/NYC_VLR_2018_FINAL.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/Santana_de_Parnai%CC%81ba_2030_Vision_%20Connected_to_the%20Future.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/Sustainability-Strategy-for-North-Rhine-Westphalia.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/The-Region-of-Valencia-and-the-local-implementation-of-the-SDGs-A-region-committed-to-Cooperation-and-the-2030-Agenda-for-Sustainable-Development.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/Voluntary%20Subnational%20Report%20-%20Maria%20Elias.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/buenos_aires_voluntary_local_review_1_0.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/english-vlr-toyama-city-japan-2018.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/kitakyushu-sdg-report-en-2018.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/ods_gamlp_compressed.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/odssp_en.pdf",
        "https://sdgs.un.org/sites/default/files/2020-09/shimokawa-city-hokkaido-sdgs-report-en-2018.pdf",
        "https://sdgs.un.org/sites/default/files/2020-10/2020%20VLR%20Stuttgart%20eng.pdf",
        "https://sdgs.un.org/sites/default/files/2020-10/Cauayan-City-Localizing-Sustainable-Development-Goals.pdf",
        "https://sdgs.un.org/sites/default/files/2020-10/Espan%CC%83ol_Informe%20de%20Localizacio%CC%81n%20de%20los%20Objetivos%20de%20Desarrollo%20Sostenible%20en%20la%20Ciudad%20de%20Sa%CC%83o%20Paulo.pdf",
        "https://sdgs.un.org/sites/default/files/2020-10/Lebenswertes%20Stuttgart_Die%20globale%20Agenda%202030%20auf%20lokaler%20Ebene.pdf",
        "https://sdgs.un.org/sites/default/files/2020-10/Portugue%CC%82s_Relato%CC%81rio%20de%20Localizac%CC%A7a%CC%83o%20dos%20Objetivos%20de%20Desenvolvimento%20Sustenta%CC%81vel%20na%20Cidade%20de%20Sa%CC%83o%20Paulo.pdf",
        "https://sdgs.un.org/sites/default/files/2020-10/SPW%20-%20Rapport%20indicateurs%20ODD-def_0.pdf",
        "https://sdgs.un.org/sites/default/files/2020-10/Turku%20Voluntary%20Local%20Review%202020%20WEB%20EN.pdf",
        "https://sdgs.un.org/sites/default/files/2020-10/VLR%20BA%202020_eng.pdf",
        "https://sdgs.un.org/sites/default/files/2020-10/VLR_State%20of%20Para%CC%81_Brazil_English.pdf",
        "https://sdgs.un.org/sites/default/files/2020-10/Voluntary-Local-Review-Bericht-englisch.pdf",
        "https://sdgs.un.org/sites/default/files/2020-10/basque2017.pdf",
        "https://sdgs.un.org/sites/default/files/2020-10/basque2018.pdf",
        "https://sdgs.un.org/sites/default/files/2020-10/basque2019.pdf",
        "https://sdgs.un.org/sites/default/files/2020-12/Pittsburgh%20VLR%202020%20Final%20Draft.pdf",
        "https://sdgs.un.org/sites/default/files/2021-01/Montevideo%20LVR%202020.pdf",
        "https://sdgs.un.org/sites/default/files/2021-01/VLR%20Guangzhou%2C%20China-compressed.pdf",
        "https://sdgs.un.org/sites/default/files/2021-03/EspooVLR2020Websmall.pdf",
        "https://sdgs.un.org/sites/default/files/2021-03/VLR%20YucatanISV_ESP_small.pdf",
        "https://sdgs.un.org/sites/default/files/2021-03/VLR%20YucatanISV_ING_small.pdf",
        "https://sdgs.un.org/sites/default/files/2021-04/Mexico%20City%20VLR.pdf",
        "https://sdgs.un.org/sites/default/files/2021-04/odssp-port.pdf",
        "https://sdgs.un.org/sites/default/files/2021-07/Agenda%202030%20in%20Asker%2C%20Voluntary%20Local%20Review%202021%20%281%29.pdf",
        "https://sdgs.un.org/sites/default/files/2021-07/Helsingborg_VLR_2021%20%282%29.pdf",
        "https://sdgs.un.org/sites/default/files/2021-07/Helsinki_VLR_From%20Agenda%20to%20Action%202021%20%281%29_0.pdf",
        "https://sdgs.un.org/sites/default/files/2021-07/Stockholm%20Volontary%20Local%20Review%202020_Agenda2030%20eng.pdf",
        "https://sdgs.un.org/sites/default/files/2021-07/VF_CDMX.pdf",
        "https://sdgs.un.org/sites/default/files/2021-07/VLR%20SDGs%20Shah%20Alam.pdf",
        "https://sdgs.un.org/sites/default/files/2021-07/VLR%20SDGs%20Subang%20Jaya.pdf",
        "https://sdgs.un.org/sites/default/files/2021-08/Mexico_Merida.pdf",
        "https://sdgs.un.org/sites/default/files/2021-08/Mexico_Tabasco.pdf",
        "https://sdgs.un.org/sites/default/files/2021-08/VF_Durango_ILV.pdf",
        "https://sdgs.un.org/sites/default/files/2021-10/Skiathos%20VLR%202020.pdf",
        "https://sdgs.un.org/sites/default/files/2021-11/Orlando%20VLR%202021.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-06/Barcelona%202020%20%20Informe.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-06/Barcelona_Agenda2030_Metas_Indicadores%20clave_Spanish.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-06/GladsaxeReport-VLR.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-06/ghent_sdg_voluntary_local_review_2020.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-06/las_voluntary_local_review_of_sdgs_2019.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-06/vlr_ba_2020_eng.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-07/vlr_city_of_malmo_2021_0.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-08/vf_ilv_edomex_compressed.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-09/2nd_vlr_state_of_para_brazil.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-09/ghent_sustainability_report_2021_-_focus_on_people_-_voluntary_local_review.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-09/voluntary_local_review_yiwu_0.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-10/sustainable_vantaa_belongs_to_everyone_eng.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-11/informe_local_voluntario-lima-2021_0.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-11/losangeles_2021_vlr.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-12/summary_of_voluntary_local_review_for_shkodra_2020.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-12/vleresimi_vullnetar_lokal_shkoder.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2021-12/vlr_2021_yokohama_for-web2.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-01/sao_paolo_vlr_2021_english.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-01/sao_paolo_vlr_2021_espanol.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-01/sao_paolo_vlr_2021_portugues.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-01/vf_guadalajara_2021.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-03/hawaii_vlr_aloha_2020_benchmark_report_fullreport.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-03/viken_county-local_voluntary_review_2021.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-03/vlr_surabaya2021_english_fa.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-03/winnipeg_voluntary_local_review_of_progress_2021.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-04/barcelona_vlr_2021_catalan.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-04/barcelona_vlr_2021_eng.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-04/barcelona_vlr_2021_spanish.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-04/basque_2030_agenda_monitoring_report.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-04/basque_agenda_2030_informe_seguimiento_2021.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-04/cape_town_vlr_2021.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-04/tokyo_sustainability_action.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-05/2021_vlr_stuttgart_a_livable_city.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-05/pittsburgh_vlr2020.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-06/tampere_fi_vlr_city_of_sustainable_action_2022.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-07/2018_suwon_voluntaryreport_goal11.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-07/2020_dangjin_vlr.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-07/2021_seodaemun-gu_sustainable_development_report.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-07/2021suwonsdgsactionreport_0.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-07/informe_voluntario_local_cordoba_2022-arg_baja.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-07/lombardy_voluntary-local-review-rl-eng-high-quality_english.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-07/lombardy_voluntary-local-review-rl-ita-high-quality_italian.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-07/toyota_city_vlr_2022.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-07/vlr_city_of_hanover.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-07/vlr_cordoba_2022-arg_baja.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-08/3_rlv_governo_do_estado_do_para_2022.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-08/3rd_vlr_state_government_of_para_2022.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-08/city_of_kiel_voluntary_local_review_2022.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-08/informe_voluntario_2021.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-08/rlv-pereira-final-hq-colombia.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-08/rvl_sanjusto_digital.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-08/vlr_dusseldorf_2022.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-08/vlr_on_the_sdgs-city_council_penang_island.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-08/vlr_santa_fe.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-10/ba_vlr_2022_english.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-10/ba_vlr_2022_espanol.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-10/vlr_gladsaxe_2022.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-11/barueri-vlr_2022.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-11/barueri_executive_summary.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-11/bristol_vlr_2022.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-11/vlr_bonn_2022.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/220929-vlr_amman.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/catamarca.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/chaco.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/chubut_0.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/corrientes.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/digital_rlv_mixco_reduced.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/entre_rios.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/la_pampa.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/la_rioja.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/misiones.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/municipio_de_bragado.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/municipio_de_partido_de_la_costa.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/municipio_de_rio_grande.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/municipio_de_san_justo.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/municipio_de_santa_fe.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/municipio_de_villa_maria.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/municipio_de_yerba_buena-tucuman.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/neuquen.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/san_juan_1.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/santafe.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/sao-paulo-executive_summary_ii_sdg_report.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/tierradelfuego.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/tucuman.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2022-12/vlr_amsterdam.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-01/informeprovinciadesalta.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-01/sdcc_dki_jakarta_vlr.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-02/vlr-relatorio_ods_casa_civil_0.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-04/barcelona_anual_monitoring_report_2030_agenda_vlr_2022_eng.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-04/barcelona_informe_anual_seguiment_agenda_2030_vlr2022_cat.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-04/barcelona_informe_anual_seguimiento_agenda2030_vlr2022_esp.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-04/bolivia_el_alto_2022_es.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-04/bolivia_la_paz_2022_es.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-04/bolivia_santa_cruz_de_la_sierra_2022_es-2.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-04/braga_vlr_2019.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-04/braga_vlr_executive_summmary.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-04/filadelfia_ods_02-03-23_v03.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-04/vlr_dortmund_2022_digital_0.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-05/6_informe_voluntario_de_seguimiento_agenda_2030_euskadi.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-05/6th_monitoring_report_2030_agenda_basque_country.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-05/lvrmontevideoods2022vf1.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-05/vlr_oaxaca_2022.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-05/vlr_of_city_of_yangzhou.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-06/helsinki-from-agenda-to-action-2023.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-06/isv_2023_tizayuca.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-06/londons_progress_towards_the_un_sdgs.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-06/vlr2022_cascais_portugal.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-06/vlr_buenos_aires_2021.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-06/vlr_buenos_aires_2021_sp.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-06/vlr_melbourne.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-08/alor_gajah_vlr.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-08/buenosairesvlr2023_eng.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-08/buenosairesvlr2023_spa.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-08/hawaii_vlr_2023.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-08/mafra_vlr_ods_en.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-08/puebla_informe_sub_voluntario.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-08/sepang_vlr_2023.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-08/tokyo_sustainability_action_2023.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-08/vlr_francisco_morato_eng.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-08/vlr_francisco_morato_port.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-08/vlr_francisco_morato_spa.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-08/vlr_ghent_2022.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-08/vlr_kuala_lumpur.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-08/vlr_mwanza.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-08/vsr_selangor.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-10/matosinhos_vlr.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-10/melaka-vlr2022.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-10/montevideo_tercer_informe_local_voluntario_ods-2023.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-10/sustainable_vantaa_belongs_to_everyone_2023.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-11/eng_vlr_16_municipalities.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2023-11/rlv_relatorio_final_10.12.2020_0.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-01/agadir_vlr-english.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-01/agadir_vlr-french.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-01/brisbane_2023_en.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-01/mexicostate-vlr-2023.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-02/agios_dimitrios_vlr_2023.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-02/beheira_executive_summary.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-02/executive_summary_of_bergens_vlr.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-02/fayoum_executive_summary.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-02/fayoum_vlr.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-02/lviv_vlr_eng.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-02/lviv_vlr_ukr.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-02/para_relatorioods_2023_br.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-02/para_reviewsdg_2023_en.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-02/part1-status_for_bergen.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-02/part2-status_for_bergen.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-02/part3-status_for_bergen.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-02/port_said_executive_summary.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-02/vlr_joensuu_finland.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-02/vlr_joensuu_report_summary_final.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-04/coronel_oviedo_odm_resiliente.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-04/ilv_cordoba_2023_0.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-04/ilv_queretaro_2023.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-04/ilv_sf_rincon_2023.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-04/informe-voluntario-local-provincia-de-cordoba-2023_arg.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-04/vlr_kibaha.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-05/2022_shanghai_vlr_china_r.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-05/7_informe_seguimiento_2023_agenda_2030_cast_web.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-05/7_jarraipen_txostena_2023_agenda_2030_eusk.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-05/7th_monitoring_report_2023_agenda_2030_engl.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-05/ilv_chiapas_2023.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-05/rlv_ennour_2024_0.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-06/2022_canelones_vlr.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-06/2022_cordoba_vlr.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-06/2022_istanbul_vlr.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-06/2022_quintana_roo_vlr.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-06/2022_tekax_vlr.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-06/2023_freiburg_vlr.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-06/2023_hamburg_vlr_report_german.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-06/2023_hamburg_vlr_summary_german.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-06/ilv_vf_queretaro_2024.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-06/voluntary_local_review_aland_2024.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-07/vlr_almaty_2023.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-07/vlr_jambi_city_2023.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-07/vlr_sado_city_2024.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-07/voluntary_local_review_montevideo_2024_uruguay.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-07/voluntary_local_review_tierp_2024.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-07/voluntary_subnational_review_nordic_region_2024_0.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-07/voluntary_subnational_review_nordic_region_2024_1.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-07/voluntary_subnational_review_nordic_region_2024_2.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-07/voluntary_subnational_review_nordic_region_2024_3.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-07/voluntary_subnational_review_nordic_region_2024_4.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-08/informe_local_voluntario_ocoyoacac._edomex.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-08/informe_local_voluntario_santa_maria_del_oro.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-08/informesubnacionalvoluntario2024_v7.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-08/revision_local_voluntaria_gobierno_municipal_de_zapopan.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-09/buffalo_city_metro_municipality_vlr_report_2024_0.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-09/city_of_tshwane_vlr_report_2024.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-09/informe_local_voluntario_ilv_ods_campo_aceval_2023.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-09/koukamma_local_municipality_vlr_report_2024.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-09/maringa_relatorio_local_voluntario.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-09/maringa_voluntary_local_review.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-09/mogale_city_local_municipality_vlr_report_2024_0.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-09/mossel_bay_local_municipality_vlr_report_2024.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-09/primer_informe_local_voluntario_fram_2023.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-09/rustenburg_local_municipality_vlr_report_2024.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-09/umhlathuze_local_municipality_vlr_report_2024.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-09/voluntary_local_review_sdgs_jawa_barat_indonesian.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-09/voluntary_subnational_review_norway.pdf",
        "https://sdgs.un.org/sites/default/files/vlrs/2024-09/west_java_sdgs_voluntary_local_review_english.pdf",
        "https://sustainabledevelopment.un.org/content/documents/10446Executive%20Summary%20Review_ROK.pdf",
        "https://sustainabledevelopment.un.org/content/documents/10611Finland_VNR.pdf",
        "https://sustainabledevelopment.un.org/content/documents/10686HLPF-Bericht_final_EN.pdf",
        "https://sustainabledevelopment.un.org/content/documents/10692NORWAY%20HLPF%20REPORT%20-%20full%20version.pdf",
        "https://sustainabledevelopment.un.org/content/documents/10729Rapport%20ODD%20France.pdf",
        "https://sustainabledevelopment.un.org/content/documents/12644VNR%20Colombia.pdf",
        "https://sustainabledevelopment.un.org/content/documents/15070Argentina(Spanish)officialsubmission.pdf",
        "https://sustainabledevelopment.un.org/content/documents/15705Indonesia.pdf",
        "https://sustainabledevelopment.un.org/content/documents/15801Brazil_Portuguese.pdf",
        "https://sustainabledevelopment.un.org/content/documents/16013Denmark.pdf",
        "https://sustainabledevelopment.un.org/content/documents/16109Netherlands.pdf",
        "https://sustainabledevelopment.un.org/content/documents/16117Argentina.pdf",
        "https://sustainabledevelopment.un.org/content/documents/16289Jordan.pdf",
        "https://sustainabledevelopment.un.org/content/documents/16341Italy.pdf",
        "https://sustainabledevelopment.un.org/content/documents/16626Guatemala.pdf",
        "https://sustainabledevelopment.un.org/content/documents/19877IVN_ODS_PY_2018_book_Final.pdf",
        "https://sustainabledevelopment.un.org/content/documents/20125INFORME_NACIONAL_VOLUNTARIO_060718.pdf",
        "https://sustainabledevelopment.un.org/content/documents/20257ALBANIA_VNR_2018_FINAL2.pdf",
        "https://sustainabledevelopment.un.org/content/documents/20312Canada_ENGLISH_18122_Canadas_Voluntary_National_ReviewENv7.pdf",
        "https://sustainabledevelopment.un.org/content/documents/203295182018_VNR_Report_Spain_EN_ddghpbrgsp.pdf",
        "https://sustainabledevelopment.un.org/content/documents/20338RNV_Versio769n_revisada_31.07.18.pdf",
        "https://sustainabledevelopment.un.org/content/documents/20470VNR_final_approved_version.pdf",
        "https://sustainabledevelopment.un.org/content/documents/23366Voluntary_National_Review_2019_Philippines.pdf",
        "https://sustainabledevelopment.un.org/content/documents/23402RSA_Voluntary_National_Review_Report___The_Final_24_July_2019.pdf",
        "https://sustainabledevelopment.un.org/content/documents/23678UK_12072019_UK_Voluntary_National_Review_2019.pdf",
        "https://sustainabledevelopment.un.org/content/documents/2380320190708_Final_VNR_2019_Indonesia_Rev3.pdf",
        "https://sustainabledevelopment.un.org/content/documents/24309Informe_Nacional_Voluntario__Uruguay_2019.pdf",
        "https://sustainabledevelopment.un.org/content/documents/25008REVISIN_NACIONAL_COMPLETA.pdf",
        "https://sustainabledevelopment.un.org/content/documents/26265VNR_Report_Finland_2020.pdf",
        "https://sustainabledevelopment.un.org/content/documents/26326VNR_2020_Peru_Report_Spanish.pdf",
        "https://sustainabledevelopment.un.org/content/documents/26386VNR_2020_Argentina_Report_Spanish.pdf",
        "https://sustainabledevelopment.un.org/content/documents/279422021_VNR_Report_Spain.pdf",
        "https://sustainabledevelopment.un.org/content/documents/279532021_VNR_Report_Denmark.pdf",
        "https://sustainabledevelopment.un.org/content/documents/279582021_VNR_Report_Sweden.pdf",
        "https://sustainabledevelopment.un.org/content/documents/280812021_VNR_Report_China_English.pdf",
        "https://sustainabledevelopment.un.org/content/documents/280842021_VNR_Report_China_Chinese.pdf",
        "https://sustainabledevelopment.un.org/content/documents/280892021_VNR_Report_Indonesia.pdf",
        "https://sustainabledevelopment.un.org/content/documents/28230Bolivias_VNR_Report.pdf",
        "https://sustainabledevelopment.un.org/content/documents/28233Voluntary_National_Review_2021_Norway.pdf",
        "https://sustainabledevelopment.un.org/content/documents/282692021_VNR_Report_Paraguay.pdf",
        "https://sustainabledevelopment.un.org/content/documents/282902021_VNR_Report_Colombia.pdf",
        "https://sustainabledevelopment.un.org/content/documents/285982021_VNR_Report_Malaysia.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/barcarena_2017_pt_1.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/barcelona_2019_cat.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/basque_country_2017_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/basque_country_2017_eu.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/basque_country_2018_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/belo_horizonte_2020_pt.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/besancon_2019_fr.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/bristol_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/buenos_aires_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/buenos_aires_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/busia_county_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/canterbury_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/cauayan_city_2017_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/chimbote_2020_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/ciudad_valles_2020_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/deqing_2017_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/deqing_2018_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/espoo_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/ghent_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/gladsaxe_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/gothenburg_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/hamamatsu_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/harare_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/hawai_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/helsinki_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/jaen_2019_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/kelowna_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/kitakyushu_2018_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/kwale_county_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/la_paz_2018_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/liverpool_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/los_angeles_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/malaga_2018_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/mannheim_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/marsabit_county_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/mexico_city_2017_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/montevideo_2020_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/new_taipei_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/new_york_2018_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/new_york_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/niort_2020_fr.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/niteroi_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/north_rhine_westphalia_2016_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/oaxaca_2019_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/para_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/pittsburgh_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/rio_2020_pt.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/santa_fe_2019_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/santana_de_parnaiba_2019_pt_1.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/scotland_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/shimokawa_2018_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/suwon_2018_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/sydney_2018_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/taipei_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/taipei_city_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/taita_taveta_county_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/toyama_2018_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/trujillo_2020_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/turku_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/valencia_region_2016_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/victoria_falls_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/wallonia_2017_fr.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/winnipeg_2018_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/winnipeg_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/06/yucatan_2020_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/asia-pacific_regional_guidelines_on_vlrs_0.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/asker_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/bergen_2021_no.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/bonn_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/buenos_aires_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/european_handbook_for_sdg_voluntary_local_reviews_online.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/florence_2021_it.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/globalguidingelementsforvlrs_final.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/helsingborg_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/malaysia_sdg_cities_booklet-2.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/malmo_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/romsdal_2021_no.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/shimokawamethodfinal.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/state_of_the_vlrs_2021.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/stateofthevoluntarylocalreview2020-final.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/stockholm_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/tokyo_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/uk-cities-voluntary-local-review-handbook.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/uppsala_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/viken_2020_no.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/vlr_agenda2030.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/vlr_handbook_7.7.19.pdf",
        "https://unhabitat.org/sites/default/files/2021/07/vlr_sdgs_shah_alam.pdf",
        "https://unhabitat.org/sites/default/files/2021/09/cordoba_2020_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/09/dangjin_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/09/durango_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/09/durango_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/09/guadalajara_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/09/helsinki_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/09/merida_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/09/mexico_city_2019_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/09/mexico_city_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/09/mexico_state.pdf",
        "https://unhabitat.org/sites/default/files/2021/09/tabasco_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/09/taoyuan_2020_e.pdf",
        "https://unhabitat.org/sites/default/files/2021/10/basque_country_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/10/besancon_2018_fr.pdf",
        "https://unhabitat.org/sites/default/files/2021/10/lincoln_2016_2017_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/10/lincoln_2018_2019_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/10/los_angeles_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/10/orlando_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/10/para_2021_en_1.pdf",
        "https://unhabitat.org/sites/default/files/2021/10/taipei_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/12/izmir_2021_tr.pdf",
        "https://unhabitat.org/sites/default/files/2021/12/lima_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2021/12/shkodra_2021_sq.pdf",
        "https://unhabitat.org/sites/default/files/2021/12/skiathos_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/12/sultanbeyli_2021_tr_1.pdf",
        "https://unhabitat.org/sites/default/files/2021/12/vantaa_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/12/yiwu_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2021/12/yokohama_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/abruzzo_marche_umbria_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/barcelona_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/basque_country_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/cape_town_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/cordoba_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/genova_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/kaohsiung_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/lazio_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/liguria_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/lombardy_milan_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/melbourne_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/messina_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/new_taipei_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/puglia_bari_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/reggio_calabria_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/roma_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/sao_paulo_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/sardinia_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/stuttgart_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/taichung_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/villa_maria_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2022-07/yunlin_county_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/01/accra_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/01/jaen_2020_es.pdf",
        "https://unhabitat.org/sites/default/files/2022/01/karatay_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/01/karatay_2021_tr.pdf",
        "https://unhabitat.org/sites/default/files/2022/01/ngora_district_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/01/vsrguidelines_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/01/yaounde_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/06/tampere_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/06/voluntarylocalreview-abridgebetweenglobalgoalsandlocalreality_2022_en_1.pdf",
        "https://unhabitat.org/sites/default/files/2022/08/buenosaires_2022_sp-optimized_2.pdf",
        "https://unhabitat.org/sites/default/files/2022/08/dhulikhel_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/08/dusseldorf_2022_en-optimized.pdf",
        "https://unhabitat.org/sites/default/files/2022/08/guidelines_en-optimized.pdf",
        "https://unhabitat.org/sites/default/files/2022/08/santafe_2022_es-optimized.pdf",
        "https://unhabitat.org/sites/default/files/2022/08/seodaemun-gu_2021_en_2.pdf",
        "https://unhabitat.org/sites/default/files/2022/08/singra_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/08/toyota_2022_en-optimized.pdf",
        "https://unhabitat.org/sites/default/files/2022/08/vicuna_mackenna_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2022/09/bonn_2022_en_1.pdf",
        "https://unhabitat.org/sites/default/files/2022/09/hanover_2020_en-optimized-optimized.pdf",
        "https://unhabitat.org/sites/default/files/2022/09/kiel_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/09/surabaya_2021_en-optimized.pdf",
        "https://unhabitat.org/sites/default/files/2022/10/amman_vlr_-_english_version_-_complete_-_out_for_print_-_in_spreads_4.pdf",
        "https://unhabitat.org/sites/default/files/2022/10/avcilar_2022_en_-_smaller_2.pdf",
        "https://unhabitat.org/sites/default/files/2022/10/barcelona_2020_cat.pdf",
        "https://unhabitat.org/sites/default/files/2022/10/bristol_2022_en_0.pdf",
        "https://unhabitat.org/sites/default/files/2022/10/ghent_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/10/pereira_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2022/10/sanjusto_2022_es-min.pdf",
        "https://unhabitat.org/sites/default/files/2022/10/suwon_2021_en_1.pdf",
        "https://unhabitat.org/sites/default/files/2022/10/tainan_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/10/wales_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/10/winnipeg_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/11/amman_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/11/buenosaires_2022_en-optimized.pdf",
        "https://unhabitat.org/sites/default/files/2022/11/cordoba_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2022/11/para_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/11/stuttgart_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/11/stuttgart_2022_gr.pdf",
        "https://unhabitat.org/sites/default/files/2022/12/amsterdam_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2022/12/barueri_2022_pt.pdf",
        "https://unhabitat.org/sites/default/files/2022/12/manizales_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2022/12/salta_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2022/12/taoyuan_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/01/cochabamba_2022_es-2.pdf",
        "https://unhabitat.org/sites/default/files/2023/01/el_alto_2022_es-2.pdf",
        "https://unhabitat.org/sites/default/files/2023/01/jakarta_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/01/la_paz_2022_es-2.pdf",
        "https://unhabitat.org/sites/default/files/2023/01/santa_cruz_de_la_sierra_2022_es-2.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/al_madinah_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/amman_2022_ar.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/atenas_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/atenas_2023_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/belen_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/belen_2023_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/bragado_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/catamarca_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/chaco_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/chubut_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/corrientes_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/entre_rios_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/escazu_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/escazu_2023_es_1.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/ghent_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/gladsaxe_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/goicoechea_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/goicoechea_2023_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/la_costa_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/la_pampa_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/la_rioja_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/madrid_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/marmara_region_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/misiones_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/neuquen_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/puriscal_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/puriscal_2023_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/rio_grande_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/san_juan_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/santa_fe_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/sarchi_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/sarchi_2023_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/tierra_del_fuego_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/tucuman_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/viken_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/03/yerba_buena_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/04/alhaurin_de_la_torre_2019_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/04/barcelona_2022_cat.pdf",
        "https://unhabitat.org/sites/default/files/2023/04/barcelona_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/04/barcelona_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/04/basque_country_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/04/cascais_2020_pt.pdf",
        "https://unhabitat.org/sites/default/files/2023/04/castilla_la_mancha_2019_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/04/london_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/04/sao_paulo_state_2022_pt.pdf",
        "https://unhabitat.org/sites/default/files/2023/05/agenda_ebc2030.pdf",
        "https://unhabitat.org/sites/default/files/2023/05/barcelona_agenda2030_metas_indicadores_clave_spanish.pdf",
        "https://unhabitat.org/sites/default/files/2023/05/barcelona_agenda2030targets_keyindicators_english.pdf",
        "https://unhabitat.org/sites/default/files/2023/05/basque_monitoring_report_2020-agenda2030.pdf",
        "https://unhabitat.org/sites/default/files/2023/05/the-region-of-valencia-and-the-local-implementation-of-the-sdgs-a-region-committed-to-cooperation-and-the-2030-agenda-for-sustainable-development.pdf",
        "https://unhabitat.org/sites/default/files/2023/05/turku_vlr_2022.pdf",
        "https://unhabitat.org/sites/default/files/2023/06/bhopal_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/06/cascais_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/06/mwanza_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/06/thunder_bay_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/06/vitoria-gasteiz_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/07/alor_gajah_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/07/buenos_aires_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/07/buenos_aires_2023_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/07/changhua_county_2023_zh-hant.pdf",
        "https://unhabitat.org/sites/default/files/2023/07/helsinki_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/07/lienchiang_county_2023_zh-hant.pdf",
        "https://unhabitat.org/sites/default/files/2023/07/manabi_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/07/sepang_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/07/tizayuca_2023_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/07/tokyo_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/08/cordoba_2023_en_1.pdf",
        "https://unhabitat.org/sites/default/files/2023/08/cordoba_2023_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/08/melaka_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/08/vantaa_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/09/hawaii_2023_en_1.pdf",
        "https://unhabitat.org/sites/default/files/2023/09/mafra_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/09/montevideo_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/09/montevideo_2023_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/09/ortiz-moyaetal.2023-stateofthevoluntarylocalreviews2023follow-upandreviewofthe2030agendaatthelocallevel.pdf",
        "https://unhabitat.org/sites/default/files/2023/10/agadir_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/10/agadir_2023_fr.pdf",
        "https://unhabitat.org/sites/default/files/2023/10/antioquia_2021_escompressed.pdf",
        "https://unhabitat.org/sites/default/files/2023/10/basque_country_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/10/belo_horizonte_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/10/bogota_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/10/dortmund_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/10/filadelfia_paraguay_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/10/kuala_lumpur_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/10/oaxaca_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/10/selangor_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/10/yangzhou_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/11/bergen_no_2021.pdf",
        "https://unhabitat.org/sites/default/files/2023/11/bergen_no_2023.pdf",
        "https://unhabitat.org/sites/default/files/2023/11/fatih_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2023/11/fatih_2023_tr.pdf",
        "https://unhabitat.org/sites/default/files/2023/11/rapa_nui_2023_es.pdf",
        "https://unhabitat.org/sites/default/files/2023/12/frankfurt_2020_de.pdf",
        "https://unhabitat.org/sites/default/files/2023/12/shanghai_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/01/bijeljina_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/01/emboreet_village-manyara_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/01/kibaha_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/02/malaga_2019_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/02/malaga_2020_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/02/malaga_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/02/malaga_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/02/mixco_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/02/shinan-gun_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/02/suwon_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/2023_-_barcelona_english.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/2023_-_lviv_english.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/2023_espoo_vlr.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/2023_hamburg_vlr_english.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/agios_dimitrios_2023.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/beheira_vlr.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/emboreet_village_manyara_2023.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/francisco_morato_2023_0.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/freiburg_2024.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/ghent-vlr-2023.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/hsinchu_city_2023.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/ilv_sf_rincon_2023.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/ilv_vf_kanasin2023.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/imbabura_2024.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/informe_local_voluntario_manabi_2023_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/karatay_2023.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/matosinhos_2023.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/port_said_vlr.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/stuttgart-a_livable_city_1.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/sustainability_report_for_the_city_of_oslo.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/taichung_2023.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/tandil_2023.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/torres_vedras_2024.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/utrecht-vlr-2023.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/villa_maria_2022.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/vlr_bad_kostritz_en_2023.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/vlr_from_gladsaxe_2023.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/vlr_fuerstenfeldbruck_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/vlr_koeln_en_2023.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/voluntary_review_of_the_city_of_rottenburg_am_neckar_2023_.pdf",
        "https://unhabitat.org/sites/default/files/2024/07/yunlin_county_2023.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/almaty_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/braga_2019_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/bungoma_2024_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/canelones_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/chiapas_2023_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/dki_jakarta_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/elgeyo_2024_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/ennour_2024_fr.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/freiburg_2024_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/guangzhou_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/istanbul_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/kakamega_2024_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/lviv_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/lviv_2023_ukr.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/manabi_2024_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/manabi_2024_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/mombasa_2024_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/montevideo_2024_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/municipalities_of_mozambique_2020_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/municipios_de_mocambique_2020_pt.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/mwanza_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/nakhon_si_thammarat_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/neuquen_2021_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/nyeri_2024_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/oocoyoacac_2024_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/partido_de_la_costa_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/penang_island_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/pichincha_2024_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/sado_city_2024_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/salta_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/san_justo_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/santa_maria_del_oro_municipality_2024_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/seodaemun-gu_2021_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/sydney_2017_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/tainan_2023_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/taita_taveta_2024_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/tekax_2022_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/tierp_2024_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/tierp_2024_se.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/turku_2022_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/valles_oriental_2023_ca.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/villa_maria_2023_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/vlr_progress_report_of_karatay_-_konya_2023_-_turkish.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/wallonia_2019_fr.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/wallonia_2023_fr.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/west_java_2024_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/west_pokot_2024_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/08/zapopoan_2024_es.pdf",
        "https://unhabitat.org/sites/default/files/2024/10/chandragiri_2024_en.pdf",
        "https://unhabitat.org/sites/default/files/2024/10/everyone_can_flourish_on_the_island_of_peace_-_aland_voluntary_review_2024_1.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-01/2021%20-%20Jakarta.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-01/2023%20-%20Taipei_s.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-01/2023%20Taichung%20City%20VLR_s.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-02/2023 - Hsinchu City.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-02/2023 - Yunlin County.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-02/2023%20-%20Agios%20Dimitrios.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-02/2023%20-%20Fuerstenfeldbruck_German.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-02/2023%20-%20Yunlin%20County.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-03/2023 - Rottenburg am Neckar.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-03/2023%20-%20Hamburg_English.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-03/2023%20-%20Hamburg_German.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-04/2023%20-%20Barcelona_Catalan.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-04/2023%20-%20Barcelona_English.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-04/2023%20-%20Barcelona_Spanish.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-04/2023%20-%20Ghent.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-04/2023%20-%20Gladsaxe.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-04/2023%20-%20Lviv_English.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-04/2023%20-%20Lviv_Ukranian.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-05/2023%20-%20Fatih.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-07/2023 - Jambi_English.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-07/2024%20-%20Sado%20City_English.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-07/2024%20-%20Sado%20City_Japanese.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-07/2024%20-%20West%20Java_English.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-10/2023%20-%20Pittung.pdf",
        "https://www.iges.or.jp/sites/default/files/2024-10/2023%20-%20Stuttgart.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2018%20-%20New%20York.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2019%20-%20Helsinki.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2019%20-%20La%20Paz.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2019%20-%20Los%20Angeles.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2019%20-%20New%20Taipei.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2019%20VLR%20Province%20of%20Jaen.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2020%20-%20Cordoba%20-%20Spanish.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2020%20-%20Espoo.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2020%20-%20Ghent.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2020%20-%20Hawai%E2%80%98i.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2020%20-%20Liverpool.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2020%20-%20Montevideo.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2020%20-%20Niteroi.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2020%20-%20Pittsburgh.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2020%20-%20Rio%20de%20Janeiro%20-%20Portuguese.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2020%20-%20Stuttgart.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2020%20-%20Turku.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2020%20Taipei%20City%20Voluntary%20local%20review.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2020%20VLR%20Province%20of%20Jaen.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Asker.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Barcelona.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Cape%20Town.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20City%20of%20M%C3%A9rida.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Florence%20-%20Italian.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Ghent.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Gladsaxe.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Helsinki.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Karatay%20v2.0.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Madrid.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Malmo.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20New%20Taipei.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Orlando.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Shah%20Alam.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Skiathos.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Stuttgart.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Subang%20Jaya.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Sultanbeyli%2C%20English.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Suwon.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Taichung%20City.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Tainan%20City_m.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Tokyo.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Vantaa.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Yokohama.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20-%20Yunlin%20County_m.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20Kaohsiung%20City%20Voluntary%20Local%20Review%20.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021%20Taipei%20City%20Voluntary%20Local%20Review.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2021-Kelowna.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Amman.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Atenas.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Avcilar.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Belen.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Bonn.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Bristol.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Cascais.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Cochabamba.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Dhulikhel.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Dusseldorf.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20El%20Alto.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Escazu.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Ghent.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Gladsaxe.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Goicoechea.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Kiel.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20La%20Paz.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Manizales.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Melbourne.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Montevideo.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Puriscal.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Santa%20Cruz%20de%20la%20Sierra.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Sarchi.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Seodaemun-gu.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Singra_0.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Tampere.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Taoyuan.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20-%20Winnipeg.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2022%20Suwon%20SDG%20Report.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2023%20-%20Alor%20Gajah%20.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2023%20-%20Buenos%20Aires_English.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2023%20-%20Buenos%20Aires_Spanish.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2023%20-%20Hawai%27i.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2023%20-%20Helsinki.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2023%20-%20Kuala%20Lumpur.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2023%20-%20Mafra.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2023%20-%20Melaka%20City.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2023%20-%20Montevideo.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2023%20-%20NST%20Voluntary%20Local%20Reviews%202022.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2023%20-%20Sepang.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2023%20-%20Shinan-gun.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2023%20-%20Tainan%20City.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2023%20-%20Tokyo.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/2023%20-%20Vantaa.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/Anual%20monitoring%20report%202030%20Agenda%20Barcelona%20VLR%202022%20ENG.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/Barcelona%E2%80%99s%202030%20Agenda%20-%20SDG%20targets%20and%20key%20indicators_0.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/Dangjin%20VLR_0.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/Hamamatsu.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/Informe%20anual%20seguiment%20Agenda%202030%20de%20Barcelona%20VLR%202022%20CAT.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/Informe%20anual%20seguimiento%20Agenda%202030%20de%20Barcelona%20VLR%202022%20ESP.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/LosAngeles_2021_VLR.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/Santana_de_Parna%C3%ADba_2030_Vision_%20Connected_to_the%20Future.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/Suwon%20-%20Suwon%20Implementation%20Report%20on%20Goal%2011.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/Taipei%20City%20VLR%202019.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/Voluntary-Local-Review-Bericht-englisch_0.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/taoyuan%2Bcity%2Bvlr.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/vlr_2021_-_english.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/vlr_2022_ingles.pdf",
        "https://www.iges.or.jp/sites/default/files/inline-files/vlr_ba_2020_eng_1.pdf",
        "https://www.local2030.org/pdf/vlr/EspooVLR2020Web.pdf",
        "https://www.local2030.org/pdf/vlr/Informe-Voluntario-Local-CORDOBA-2022-ARG-baja.pdf",
        "https://www.local2030.org/pdf/vlr/Voluntary-Local-Review-CORDOBA-2022-ARG-baja.pdf",
        "https://www.local2030.org/pdf/vlr/aloha2020.pdf",
        "https://www.local2030.org/pdf/vlr/bristol-uk-vlr-2019.pdf",
        "https://www.local2030.org/pdf/vlr/buenos-aires-argentina-vlr-2019.pdf",
        "https://www.local2030.org/pdf/vlr/hamamatsu-city.pdf",
        "https://www.local2030.org/pdf/vlr/helsinki-city-2019.pdf",
        "https://www.local2030.org/pdf/vlr/international-affairs-vlr-2019.pdf",
        "https://www.local2030.org/pdf/vlr/las-voluntary-local-review-of-sdgs-2019.pdf",
        "https://www.local2030.org/pdf/vlr/mannheim-vlr-2020.pdf",
        "https://www.local2030.org/pdf/vlr/oaxaca-vlr-2020.pdf",
        "https://www.local2030.org/pdf/vlr/santana-de-parnaiba-brasil-vlr-2019.pdf",
        "https://www.local2030.org/pdf/vlr/taipei-city-vlr-2019.pdf",
        "https://www.local2030.org/pdf/vlr/tapei-voluntary-local-review-2020.pdf",
        "https://www.local2030.org/pdf/vlr/vlr-city-of-turku-finland-2020.pdf",
        "https://www.local2030.org/pdf/vlr/yucatan-2020-min.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/10560NVR%20%28Morocco%29.pdf",
        "https://hlpf.un.org/sites/default/files/vnrs/2021/10738egypt.pdf",
        "https://sdgs.un.org/sites/default/files/2021-04/Mexico%20City%20VLR.pdf",
        # ... (Add all other URLs here)
    ]

    for url in urls_to_scrape:
        download_pdfs_from_url(url, visited_urls, session, unique_hashes)

    logging.info("Finished scraping and downloading PDFs.")

if __name__ == "__main__":
    main()
