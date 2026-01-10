"""
Cache management for PDF processing results.

This module provides functions for caching and retrieving:
- GROBID parsing results
- Table extraction results
- Figure extraction results
- Embeddings and vector indices
"""

import os
import json
import hashlib
import logging
from typing import List, Optional, Callable, Any, Type
import numpy as np

logger = logging.getLogger(__name__)

# Cache directory for embeddings
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "embeddings_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


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
