import camelot
import tabula
import pandas as pd

import fitz
import pytesseract
from PIL import Image
import os

def extract_tables(pdf_path):
    tables_text = []

    # Camelot (best for vector PDFs)
    try:
        tables = camelot.read_pdf(pdf_path, pages="all")
        for i, t in enumerate(tables):
            tables_text.append(f"Table {i+1}:\n{t.df.to_string(index=False)}")
    except Exception:
        pass

    # Tabula fallback
    try:
        dfs = tabula.read_pdf(pdf_path, pages="all", multiple_tables=True)
        for i, df in enumerate(dfs):
            tables_text.append(f"Table (Tabula) {i+1}:\n{df.to_string(index=False)}")
    except Exception:
        pass

    return tables_text


def extract_figures(pdf_path, out_dir="figures"):
    """
    Extract figures from PDF and return image paths for multimodal analysis.
    This follows the architecture: Figures → extracted images → Multimodal GPT
    
    Args:
        pdf_path: Path to PDF file
        out_dir: Directory to save extracted images
        
    Returns:
        List of image file paths
    """
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    figure_paths = []

    for i, page in enumerate(doc):
        images = page.get_images(full=True)
        for j, img in enumerate(images):
            xref = img[0]
            pix = fitz.Pixmap(doc, xref)

            if pix.n < 5:  # GRAY or RGB
                img_path = f"{out_dir}/p{i}_img{j}.png"
                pix.save(img_path)
                figure_paths.append(img_path)

            pix = None

    doc.close()
    return figure_paths


def extract_figures_text(pdf_path, out_dir="figures"):
    """
    Legacy function: Extract figures and perform OCR.
    For multimodal analysis, use extract_figures() instead.
    """
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    figure_texts = []

    for i, page in enumerate(doc):
        images = page.get_images(full=True)
        for j, img in enumerate(images):
            xref = img[0]
            pix = fitz.Pixmap(doc, xref)

            if pix.n < 5:
                img_path = f"{out_dir}/p{i}_img{j}.png"
                pix.save(img_path)

                text = pytesseract.image_to_string(Image.open(img_path))
                if text.strip():
                    figure_texts.append(
                        f"Figure OCR (page {i+1}):\n{text.strip()}"
                    )

            pix = None

    doc.close()
    return figure_texts


import requests
from lxml import etree
import os
import time
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# Create a session with connection pooling
_session = None

def get_session():
    """Get or create a requests session with connection pooling"""
    global _session
    if _session is None:
        _session = requests.Session()
        # Configure session with better defaults
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=1,
            pool_maxsize=1,
            max_retries=0  # We handle retries ourselves
        )
        _session.mount('http://', adapter)
        _session.mount('https://', adapter)
    return _session

def get_grobid_url() -> str:
    """
    Get GROBID server URL from environment variable or auto-detect.
    
    Checks:
    1. GROBID_URL environment variable (full URL)
    2. GROBID_HOST and GROBID_PORT environment variables
    3. Auto-detection by checking common ports (8070, 8080)
    
    Returns:
        GROBID API endpoint URL
    """
    # Check for full URL in environment
    grobid_url = os.getenv("GROBID_URL")
    if grobid_url:
        # Ensure it has the API endpoint
        if not grobid_url.endswith("/api/processFulltextDocument"):
            grobid_url = grobid_url.rstrip("/") + "/api/processFulltextDocument"
        return grobid_url
    
    # Check for host and port separately
    grobid_host = os.getenv("GROBID_HOST", "localhost")
    grobid_port = os.getenv("GROBID_PORT", "8070")
    
    # Try to auto-detect if server is running on common ports
    if grobid_host == "localhost":
        for port in [grobid_port, "8070", "8080"]:
            test_url = f"http://localhost:{port}/api/isalive"
            try:
                session = get_session()
                response = session.get(test_url, timeout=2)
                if response.status_code == 200:
                    logger.info(f"[GROBID] Auto-detected GROBID on port {port}")
                    return f"http://localhost:{port}/api/processFulltextDocument"
            except (requests.exceptions.RequestException, requests.exceptions.Timeout):
                continue
    
    # Default to configured or standard port
    return f"http://{grobid_host}:{grobid_port}/api/processFulltextDocument"


def check_grobid_available() -> Tuple[bool, str]:
    """
    Check if GROBID server is available and running.
    
    Returns:
        Tuple of (is_available: bool, error_message: str)
    """
    try:
        grobid_url = get_grobid_url()
        # Extract base URL for health check
        base_url = grobid_url.replace("/api/processFulltextDocument", "")
        health_url = f"{base_url}/api/isalive"
        session = get_session()
        response = session.get(health_url, timeout=5)
        if response.status_code == 200:
            return True, ""
        else:
            return False, f"GROBID health check returned status {response.status_code}"
    except requests.exceptions.ConnectionError as e:
        base_url = get_grobid_url().replace("/api/processFulltextDocument", "")
        return False, (
            f"Could not connect to GROBID at {base_url}. "
            "Please ensure GROBID is running:\n"
            "  docker-compose -f docker-compose.grobid.yml up -d\n"
            "Or check if GROBID_URL/GROBID_HOST/GROBID_PORT environment variables are set correctly."
        )
    except requests.exceptions.Timeout:
        base_url = get_grobid_url().replace("/api/processFulltextDocument", "")
        return False, f"GROBID health check timed out at {base_url}"
    except Exception as e:
        return False, f"GROBID health check failed: {str(e)}"


def grobid_parse(pdf_path: str, max_retries: int = 3) -> dict:
    """
    Parse PDF using GROBID service with retry logic.
    
    Args:
        pdf_path: Path to PDF file
        max_retries: Maximum number of retry attempts (default: 3)
        
    Returns:
        Dictionary mapping section titles to text content
        
    Raises:
        requests.exceptions.RequestException: If GROBID server is not available after retries
        FileNotFoundError: If PDF file doesn't exist
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    # Check if GROBID is available before attempting
    is_available, error_msg = check_grobid_available()
    if not is_available:
        raise requests.exceptions.ConnectionError(error_msg)
    
    grobid_url = get_grobid_url()
    base_url = grobid_url.replace("/api/processFulltextDocument", "")
    session = get_session()
    
    # Retry logic with exponential backoff
    last_exception = None
    for attempt in range(max_retries):
        try:
            # Re-check availability before each attempt
            if attempt > 0:
                is_available, error_msg = check_grobid_available()
                if not is_available:
                    raise requests.exceptions.ConnectionError(error_msg)
                # Exponential backoff: wait 2^attempt seconds
                wait_time = 2 ** attempt
                logger.info(f"[GROBID] Retry attempt {attempt + 1}/{max_retries} after {wait_time}s...")
                time.sleep(wait_time)
            
            # Check file size and warn if very large
            file_size = os.path.getsize(pdf_path)
            if file_size > 50 * 1024 * 1024:  # > 50MB
                logger.warning(f"[GROBID] Large PDF file ({file_size / 1024 / 1024:.1f}MB) - processing may take longer")
            
            logger.info(f"[GROBID] Processing PDF: {pdf_path} (attempt {attempt + 1}/{max_retries})")
            
            with open(pdf_path, "rb") as f:
                response = session.post(
                    grobid_url,
                    files={"input": f},
                    data={"consolidateHeader": "1"},
                    timeout=(10, 600)  # Connect timeout: 10s, Read timeout: 600s (10 minutes for large PDFs)
                )
            
            response.raise_for_status()
            logger.info(f"[GROBID] Successfully parsed PDF in attempt {attempt + 1}")
            return parse_tei_xml(response.text)
            
        except requests.exceptions.ConnectionError as e:
            last_exception = e
            error_str = str(e)
            if "Remote end closed connection" in error_str or "Connection aborted" in error_str:
                logger.warning(
                    f"[GROBID] Connection error on attempt {attempt + 1}/{max_retries}: {error_str}. "
                    "GROBID may be overloaded or crashed during processing."
                )
            else:
                logger.warning(f"[GROBID] Connection error on attempt {attempt + 1}/{max_retries}: {error_str}")
            
            if attempt == max_retries - 1:
                # Last attempt failed, provide helpful error message
                raise requests.exceptions.ConnectionError(
                    f"Failed to connect to GROBID after {max_retries} attempts.\n"
                    f"Error: {error_str}\n\n"
                    f"Please verify:\n"
                    f"  1. GROBID is running: curl {base_url}/api/isalive\n"
                    f"  2. GROBID has enough memory: docker logs grobid\n"
                    f"  3. PDF file is not corrupted\n"
                    f"  4. Try restarting GROBID: docker-compose -f docker-compose.grobid.yml restart"
                )
                
        except requests.exceptions.Timeout as e:
            last_exception = e
            logger.warning(
                f"[GROBID] Timeout on attempt {attempt + 1}/{max_retries}: {str(e)}. "
                "PDF may be too large or GROBID is overloaded."
            )
            if attempt == max_retries - 1:
                raise requests.exceptions.Timeout(
                    f"GROBID request timed out after {max_retries} attempts.\n"
                    "The PDF may be too large or GROBID may be overloaded.\n"
                    "Try:\n"
                    "  1. Increasing GROBID memory: JAVA_OPTS=-Xmx8g\n"
                    "  2. Processing a smaller PDF\n"
                    "  3. Checking GROBID logs: docker logs grobid"
                )
                
        except requests.exceptions.HTTPError as e:
            # HTTP errors (4xx, 5xx) usually shouldn't be retried
            logger.error(f"[GROBID] HTTP error: {e.response.status_code} - {e.response.text[:200]}")
            raise
            
        except Exception as e:
            last_exception = e
            logger.error(f"[GROBID] Unexpected error on attempt {attempt + 1}/{max_retries}: {str(e)}")
            if attempt == max_retries - 1:
                raise
    
    # Should never reach here, but just in case
    raise requests.exceptions.RequestException(
        f"Failed to parse PDF after {max_retries} attempts. Last error: {last_exception}"
    )


def parse_tei_xml(xml_text: str) -> dict:
    root = etree.XML(xml_text.encode())
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}

    sections = {}
    for div in root.findall(".//tei:body/tei:div", ns):
        head = div.find("tei:head", ns)
        title = head.text if head is not None else "Untitled"
        paragraphs = [
            " ".join(p.itertext())
            for p in div.findall(".//tei:p", ns)
        ]
        sections[title] = "\n".join(paragraphs)

    return sections