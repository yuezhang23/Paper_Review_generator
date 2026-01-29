"""
Cache management for PDF processing results.

This module provides functions for caching and retrieving:
- GROBID parsing results
- Table extraction results
- Figure extraction results
- Embeddings and vector indices

Cache keys use a content-based fingerprint (first paragraph of the paper) when
possible, so lookup is lightweight: only the first page is read instead of the
entire PDF.
"""

import os
import re
import json
import hashlib
import logging
from typing import List, Optional, Callable, Any, Type
import numpy as np

logger = logging.getLogger(__name__)

# Cache directory for embeddings
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "embeddings_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Max characters from the beginning of the paper to use for cache key (first paragraph(s))
_FIRST_PARAGRAPH_MAX_CHARS = 2000


def extract_first_paragraph(pdf_path: str, max_chars: int = _FIRST_PARAGRAPH_MAX_CHARS) -> str:
    """
    Extract the first paragraph(s) from the PDF using only the first page.
    Lightweight: reads first page only, no full PDF or GROBID.

    Args:
        pdf_path: Path to PDF file
        max_chars: Maximum characters to include (default 2000)

    Returns:
        Normalized first-paragraph text, or empty string on failure.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("[Cache] PyMuPDF not available for first-paragraph extraction")
        return ""

    if not os.path.exists(pdf_path):
        return ""

    try:
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            doc.close()
            return ""
        page = doc[0]
        raw = page.get_text()
        doc.close()
    except Exception as e:
        logger.warning(f"[Cache] Failed to extract first paragraph: {e}")
        return ""

    # Split into paragraphs (blank-line separated), take first non-empty
    blocks = [b.strip() for b in re.split(r"\n\s*\n", raw) if b.strip()]
    if not blocks:
        return ""

    out: List[str] = []
    n = 0
    for b in blocks:
        if n + len(b) > max_chars:
            out.append(b[: max_chars - n])
            break
        out.append(b)
        n += len(b)

    text = " ".join(out)
    # Normalize: single spaces, strip
    text = re.sub(r"\s+", " ", text).strip()[:max_chars]
    return text


def get_content_based_cache_key(pdf_path: str) -> str:
    """
    Generate a cache key from the first paragraph of the paper.
    Uses only the first page (lightweight I/O). Falls back to full-PDF hash
    if extraction fails or yields empty text.

    Args:
        pdf_path: Path to PDF file

    Returns:
        Cache key string (MD5 hex)
    """
    first = extract_first_paragraph(pdf_path)
    if first:
        h = hashlib.md5(first.encode("utf-8")).hexdigest()
        logger.info(f"[Cache] Content-based key (first paragraph, {len(first)} chars)")
        return h
    logger.info("[Cache] Fallback to full-PDF hash")
    return get_pdf_hash(pdf_path)


def get_pdf_hash(pdf_path: str) -> str:
    """Generate a hash for the PDF file to use as cache key"""
    hash_md5 = hashlib.md5()
    with open(pdf_path, "rb") as f:
        # Read file in chunks to handle large files
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def _load_cache(pdf_hash: str, cache_type: str, validate_fn: Optional[Callable] = None) -> Optional[Any]:
    """Generic cache loading function"""
    cache_file = os.path.join(CACHE_DIR, f"{pdf_hash}_{cache_type}.json")
    if not os.path.exists(cache_file):
        return None
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if validate_fn:
                data = validate_fn(data)
            return data
    except Exception as e:
        logger.warning(f"[Cache] Failed to load cached {cache_type}: {str(e)}")
        return None


def _save_cache(pdf_hash: str, cache_type: str, data: Any):
    """Generic cache saving function"""
    try:
        # Ensure cache directory exists
        os.makedirs(CACHE_DIR, exist_ok=True)
        cache_file = os.path.join(CACHE_DIR, f"{pdf_hash}_{cache_type}.json")
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[Cache] Failed to save {cache_type} cache: {str(e)}")


def load_cached_grobid(pdf_hash: str) -> Optional[dict]:
    """Load cached GROBID parsing results"""
    return _load_cache(pdf_hash, "grobid")


def save_cached_grobid(pdf_hash: str, sections: dict):
    """Save GROBID parsing results to cache"""
    _save_cache(pdf_hash, "grobid", sections)


def load_cached_tables(pdf_hash: str) -> Optional[List[str]]:
    """Load cached table extraction results"""
    return _load_cache(pdf_hash, "tables")


def save_cached_tables(pdf_hash: str, tables: List[str]):
    """Save table extraction results to cache"""
    _save_cache(pdf_hash, "tables", tables)


def load_cached_figures(pdf_hash: str) -> Optional[List[str]]:
    """Load cached figure paths"""
    def validate_figures(figure_paths):
        existing_paths = [p for p in figure_paths if os.path.exists(p)]
        if len(existing_paths) != len(figure_paths):
            logger.warning("[Cache] Some cached figure files are missing, will re-extract")
            return None
        return existing_paths
    return _load_cache(pdf_hash, "figures", validate_figures)


def save_cached_figures(pdf_hash: str, figure_paths: List[str]):
    """Save figure paths to cache"""
    _save_cache(pdf_hash, "figures", figure_paths)


def load_cached_index(pdf_hash: str, VectorIndex: Type):
    """
    Load cached embeddings and index if available.
    
    Args:
        pdf_hash: Hash of the PDF file
        VectorIndex: VectorIndex class (passed to avoid circular import)
        
    Returns:
        VectorIndex instance if cache exists, None otherwise
    """
    texts_file = os.path.join(CACHE_DIR, f"{pdf_hash}_texts.json")
    embeddings_file = os.path.join(CACHE_DIR, f"{pdf_hash}_embeddings.npy")
    
    if not (os.path.exists(texts_file) and os.path.exists(embeddings_file)):
        return None
    
    try:
        logger.info(f"[Cache] Loading cached index for PDF hash: {pdf_hash[:8]}...")
        # Load embeddings
        embeddings = np.load(embeddings_file)
        
        # Load texts
        with open(texts_file, 'r', encoding='utf-8') as f:
            texts = json.load(f)
        
        # Rebuild index
        index = VectorIndex(embeddings.shape[1])
        index.add(embeddings, texts)
        
        logger.info(f"[Cache] Successfully loaded cached index with {len(texts)} entries")
        return index
    except Exception as e:
        logger.warning(f"[Cache] Failed to load cached index: {str(e)}. Will rebuild.")
        return None


def save_cached_index(pdf_hash: str, index, embeddings: np.ndarray):
    """
    Save embeddings and index to cache.
    
    Args:
        pdf_hash: Hash of the PDF file
        index: VectorIndex instance with texts attribute
        embeddings: Numpy array of embeddings
    """
    try:
        # Ensure cache directory exists
        os.makedirs(CACHE_DIR, exist_ok=True)
        
        texts_file = os.path.join(CACHE_DIR, f"{pdf_hash}_texts.json")
        embeddings_file = os.path.join(CACHE_DIR, f"{pdf_hash}_embeddings.npy")
        
        logger.info(f"[Cache] Saving index to cache for PDF hash: {pdf_hash[:8]}...")
        
        # Save embeddings
        np.save(embeddings_file, embeddings)
        
        # Save texts
        with open(texts_file, 'w', encoding='utf-8') as f:
            json.dump(index.texts, f, ensure_ascii=False, indent=2)
        
        logger.info(f"[Cache] Successfully cached index")
    except Exception as e:
        logger.warning(f"[Cache] Failed to save cache: {str(e)}")
