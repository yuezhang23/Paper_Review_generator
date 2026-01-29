import os
import time
import logging
import re
from typing import Tuple, List

import requests
from lxml import etree

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
    """
    Parse GROBID TEI XML to extract sections and figure/table captions.
    
    By default, GROBID only extracts captions for figures and tables, not their content.
    For full content extraction, use separate methods (OCR or multimodal).
    
    Returns:
        Dictionary with:
        - 'sections': Dictionary mapping section titles to text content
        - 'figure_captions': List of figure captions
        - 'table_captions': List of table captions
    """
    root = etree.XML(xml_text.encode())
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}

    sections = {}
    figure_captions = []
    table_captions = []
    
    # Extract sections
    for div in root.findall(".//tei:body/tei:div", ns):
        head = div.find("tei:head", ns)
        title = head.text if head is not None else "Untitled"
        paragraphs = [
            " ".join(p.itertext())
            for p in div.findall(".//tei:p", ns)
        ]
        sections[title] = "\n".join(paragraphs)
    
    # Extract figure captions
    for figure in root.findall(".//tei:figure", ns):
        fig_desc = figure.find("tei:figDesc", ns)
        fig_head = figure.find("tei:head", ns)
        if fig_head is not None and fig_head.text:
            caption_text = fig_head.text.strip()
            if fig_desc is not None and fig_desc.text:
                caption_text += ": " + " ".join(fig_desc.itertext()).strip()
            figure_captions.append(caption_text)
        elif fig_desc is not None and fig_desc.text:
            figure_captions.append(" ".join(fig_desc.itertext()).strip())
    
    # Extract table captions
    for table in root.findall(".//tei:figure[@type='table']", ns):
        fig_head = table.find("tei:head", ns)
        if fig_head is not None and fig_head.text:
            table_captions.append(fig_head.text.strip())
    
    # Also check for table elements directly
    for table in root.findall(".//tei:table", ns):
        table_head = table.find(".//tei:head", ns)
        if table_head is not None and table_head.text:
            table_captions.append(table_head.text.strip())

    return {
        "sections": sections,
        "figure_captions": figure_captions,
        "table_captions": table_captions
    }


def select_important_tables_figures(
    sections: dict,
    tables: List[str],
    figure_paths: List[str],
    max_tables: int = 3,
    max_figures: int = 3
) -> Tuple[List[int], List[int]]:
    """
    Select important tables and figures based on heuristics:
    - Mentioned in Abstract
    - Mentioned in Conclusion
    - Labeled "Main results"
    - Contain SOTA comparisons or ablations
    
    Args:
        sections: Dictionary of section titles to text (extracted from GROBID result)
        tables: List of table content strings
        figure_paths: List of figure image paths
        max_tables: Maximum number of tables to select
        max_figures: Maximum number of figures to select
    
    Returns:
        Tuple of (selected_table_indices, selected_figure_indices)
    """
    
    if not tables and not figure_paths:
        logger.info("[Selection] No tables or figures to select")
        return [], []
    
    # Build relevant text from Abstract, Conclusion, and main results sections
    abstract_text = sections.get("Abstract", "").lower()
    conclusion_text = sections.get("Conclusion", "").lower()
    main_results_text = " ".join(
        text.lower() for title, text in sections.items()
        if "main result" in title.lower() or "main result" in text.lower()
    )
    all_relevant_text = f"{abstract_text} {conclusion_text} {main_results_text}"
    
    # Keywords for SOTA/ablation comparisons
    sota_keywords = ["sota", "state-of-the-art", "state of the art", "best result", "competitive", "superior"]
    ablation_keywords = ["ablation", "ablate", "ablation study", "ablation analysis"]
    
    def score_items(items, item_type="table"):
        """Score items based on relevance heuristics"""
        scores = []
        for i, item in enumerate(items):
            score = 0
            item_lower = (item.lower() if isinstance(item, str) else str(item)).lower()
            
            # Check if item is mentioned in relevant sections
            refs = (
                [f"table {i+1}", f"table{i+1}", f"tab. {i+1}", f"tab.{i+1}"]
                if item_type == "table"
                else [f"figure {i+1}", f"figure{i+1}", f"fig. {i+1}", f"fig.{i+1}", f"fig {i+1}"]
            )
            for ref in refs:
                if ref in all_relevant_text:
                    score += 10
                    logger.debug(f"[Selection] {item_type.capitalize()} {i+1} mentioned in Abstract/Conclusion/Main Results")
            
            if item_type == "table":
                # Check for SOTA comparisons and ablations in table content
                for keyword in sota_keywords + ablation_keywords:
                    if keyword in item_lower:
                        score += 5
                        logger.debug(f"[Selection] Table {i+1} contains {keyword}")
                if "main result" in item_lower:
                    score += 8
                    logger.debug(f"[Selection] Table {i+1} labeled as main results")
            else:
                # For figures, first few are often important
                if i < 3:
                    score += 2
            
            scores.append((score, i))
        return scores
    
    def select_top_items(scores, max_items, item_type="table"):
        """Select top items based on scores"""
        if not scores:
            return []
        scores.sort(reverse=True, key=lambda x: x[0])
        selected = [idx for score, idx in scores[:max_items] if score > 0]
        if not selected:
            selected = list(range(min(max_items, len(scores))))
            logger.info(f"[Selection] No {item_type}s met criteria, selecting first {len(selected)}")
        else:
            logger.info(f"[Selection] Selected {len(selected)} important {item_type}s: {selected}")
        return selected
    
    # Score and select tables and figures
    table_scores = score_items(tables, "table")
    figure_scores = score_items(figure_paths, "figure")
    
    selected_tables = select_top_items(table_scores, max_tables, "table")
    selected_figures = select_top_items(figure_scores, max_figures, "figure")
    
    return selected_tables, selected_figures


def extract_metadata_from_grobid_api(pdf_path: str) -> dict:
    """
    Extract paper metadata (title, authors, year, venue) from PDF using GROBID API.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Dictionary with keys: title, authors (list), year, venue
    """
    try:
        # Get GROBID URL
        grobid_url = get_grobid_url()
        base_url = grobid_url.replace("/api/processFulltextDocument", "")
        
        # Check if GROBID is available
        is_available, error_msg = check_grobid_available()
        if not is_available:
            logger.warning(f"[Metadata] GROBID not available: {error_msg}")
            return {
                "title": "Unknown Title",
                "authors": [],
                "year": "N/A",
                "venue": "N/A"
            }
        
        # Call GROBID API to get TEI XML
        session = get_session()
        with open(pdf_path, "rb") as f:
            response = session.post(
                grobid_url,
                files={"input": f},
                data={"consolidateHeader": "1"},
                timeout=(10, 300)
            )
        response.raise_for_status()
        
        # Parse TEI XML to extract metadata
        xml_text = response.text
        root = etree.XML(xml_text.encode())
        ns = {"tei": "http://www.tei-c.org/ns/1.0"}
        
        # Extract title from teiHeader
        title_elem = root.find(".//tei:titleStmt/tei:title[@type='main']", ns)
        if title_elem is None:
            title_elem = root.find(".//tei:titleStmt/tei:title", ns)
        title = " ".join(title_elem.itertext()).strip() if title_elem is not None else "Unknown Title"
        
        # Extract authors
        authors = []
        for author in root.findall(".//tei:sourceDesc//tei:author", ns):
            first_names = []
            last_names = []
            
            # Extract first name
            first_elem = author.find(".//tei:forename", ns)
            if first_elem is not None:
                first_names.append(" ".join(first_elem.itertext()).strip())
            
            # Extract last name
            last_elem = author.find(".//tei:surname", ns)
            if last_elem is not None:
                last_names.append(" ".join(last_elem.itertext()).strip())
            
            # Combine first and last name
            if first_names or last_names:
                author_name = " ".join(first_names + last_names).strip()
                if author_name:
                    authors.append(author_name)
        
        # Extract year from publication date
        date_elem = root.find(".//tei:sourceDesc//tei:date[@type='published']", ns)
        if date_elem is None:
            date_elem = root.find(".//tei:sourceDesc//tei:date", ns)
        year = "N/A"
        if date_elem is not None:
            date_text = " ".join(date_elem.itertext()).strip()
            # Try to extract year (4 digits)
            year_match = re.search(r'\b(19|20)\d{2}\b', date_text)
            if year_match:
                year = year_match.group(0)
        
        # Extract venue/conference from sourceDesc
        venue = "N/A"
        biblscope_elem = root.find(".//tei:sourceDesc//tei:biblScope[@unit='journal']", ns)
        if biblscope_elem is None:
            biblscope_elem = root.find(".//tei:sourceDesc//tei:biblScope[@unit='conference']", ns)
        if biblscope_elem is not None:
            venue = " ".join(biblscope_elem.itertext()).strip()
        
        # If venue not found, try to extract from titleStmt/note
        if venue == "N/A":
            note_elem = root.find(".//tei:titleStmt/tei:note[@type='venue']", ns)
            if note_elem is not None:
                venue = " ".join(note_elem.itertext()).strip()
        
        metadata = {
            "title": title,
            "authors": authors,
            "year": year,
            "venue": venue
        }
        
        logger.info(f"[Metadata] Extracted metadata: title={title}, authors={len(authors)}, year={year}, venue={venue}")
        return metadata
        
    except Exception as e:
        logger.warning(f"[Metadata] Failed to extract metadata from GROBID: {str(e)}")
        return {
            "title": "Unknown Title",
            "authors": [],
            "year": "N/A",
            "venue": "N/A"
        }