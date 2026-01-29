import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import faiss
import numpy as np
import logging
import traceback
import platform
import asyncio
import threading
from typing import List, Tuple, Optional
from FlagEmbedding import FlagAutoModel
import camelot
import tabula
import fitz
from .utils_grobid import grobid_parse, select_important_tables_figures
from utils import file_storage
from openreview_service import (
    fetch_and_save_openreview_paper,
    parse_openreview_info_from_text,
    search_openreview_by_title
)
from .figure_table_ocr import (
    enrich_figures_with_ocr,
    enrich_tables_with_ocr
)
from .figure_table_multimodal import (
    enrich_figures_with_multimodal,
    enrich_tables_with_multimodal
)
from .cache import (
    get_content_based_cache_key,
    load_cached_grobid,
    save_cached_grobid,
    load_cached_tables,
    save_cached_tables,
    load_cached_figures,
    save_cached_figures,
    load_cached_index,
    save_cached_index
)
from utils import web_search_for_paper_pdf
from fastapi import HTTPException
import httpx
import tempfile

# Fix OpenMP issues on Apple Silicon (M1/M2/M3)
# Prevents "OMP: Error #179: Function Can't open SHM2 failed" errors
if platform.system() == 'Darwin' and platform.machine() == 'arm64':
    os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
    # Disable OpenMP threading to prevent conflicts with PyTorch on Apple Silicon
    os.environ['OMP_NUM_THREADS'] = '1'
    # Use single-threaded BLAS on Apple Silicon to avoid conflicts
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    os.environ['MKL_NUM_THREADS'] = '1'
    os.environ['NUMEXPR_NUM_THREADS'] = '1'

logger = logging.getLogger(__name__)

# Lazy load model to avoid loading on import
_model = None
_model_lock = threading.Lock()  # Lock for thread-safe model initialization


async def resolve_pdf_path(
    file_ids: Optional[List[str]] = None,
    paper_url: Optional[str] = None,
    paper_name: Optional[str] = None,
    use_openreview: bool = None
) -> str:
    """
    Resolve PDF file path from request parameters.
    Downloads/saves PDF if needed and returns local file path.
    
    Returns:
        Path to PDF file on local filesystem
    """
    # Priority 1: Extract from uploaded files
    if file_ids and len(file_ids) > 0:
        # Use uploaded PDFs (now saved to disk during upload)
        for file_id in file_ids:
            if file_id in file_storage:
                file_info = file_storage[file_id]
                if file_info.get('content_type') == 'application/pdf' or file_info.get('pdf_path'):
                    pdf_path = file_info.get('pdf_path')
                    if pdf_path and os.path.exists(pdf_path):
                        return pdf_path
                    else:
                        raise HTTPException(
                            status_code=404,
                            detail=f"PDF file {file_id} not found on disk. Please re-upload the file."
                        )
                        
    # Priority 2: Extract from OpenReview URL
    if paper_url and use_openreview and 'openreview.net' in paper_url:
        try:
            parsed_info = parse_openreview_info_from_text(paper_url)
            paper_ids = parsed_info.get('paper_ids', [])
            if paper_ids:
                paper_id = paper_ids[0]
                paper_data = await fetch_and_save_openreview_paper(paper_id)
                if paper_data and paper_data.get('pdf_path'):
                    return paper_data['pdf_path']
        except Exception as e:
            raise HTTPException(
                status_code=400, 
                detail=f"Error fetching paper from OpenReview: {str(e)}"
            )
    
    # Priority 3: Download from URL
    if paper_url:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(paper_url, follow_redirects=True)
                if response.status_code == 200 and 'pdf' in response.headers.get('content-type', ''):
                    # Save to temporary file
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                        tmp_file.write(response.content)
                        return tmp_file.name
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error downloading PDF from URL: {str(e)}"
            )
    
    # Priority 4: Search by paper name (OpenReview, then web search fallback)
    # if paper_name and use_openreview:
    #     openreview_404: Optional[HTTPException] = None
    #     try:
    #         logger.info(f"[Resolve PDF] Searching OpenReview for paper: {paper_name}")
    #         papers = await search_openreview_by_title(paper_name, limit=1)
    #         if papers and len(papers) > 0:
    #             matched_paper = papers[0]
    #             paper_id = matched_paper.get('id') or matched_paper.get('paper_id')
    #             if paper_id:
    #                 logger.info(f"[Resolve PDF] Found paper ID: {paper_id}, fetching PDF...")
    #                 paper_data = await fetch_and_save_openreview_paper(paper_id)
    #                 if paper_data and paper_data.get('pdf_path'):
    #                     logger.info(f"[Resolve PDF] PDF path resolved from OpenReview search: {paper_data['pdf_path']}")
    #                     return paper_data['pdf_path']
    #                 else:
    #                     openreview_404 = HTTPException(
    #                         status_code=404,
    #                         detail=f"PDF not found for paper '{paper_name}' (ID: {paper_id})"
    #                     )
    #             else:
    #                 openreview_404 = HTTPException(
    #                     status_code=404,
    #                     detail=f"Could not extract paper ID from search results for '{paper_name}'"
    #                 )
    #         else:
    #             openreview_404 = HTTPException(
    #                 status_code=404,
    #                 detail=f"No papers found matching '{paper_name}' on OpenReview"
    #             )
    #     except HTTPException as e:
    #         if e.status_code != 404:
    #             raise
    #         openreview_404 = e
    #     except Exception as e:
    #         logger.error(f"[Resolve PDF] Error searching OpenReview by name: {str(e)}")
    #         raise HTTPException(
    #             status_code=500,
    #             detail=f"Error searching for paper '{paper_name}': {str(e)}"
    #         )

    #     # Fallback: web search via AI Builder /v1/search/ when OpenReview fails (404)
    #     if openreview_404 is not None:
    #         logger.info(f"[Resolve PDF] OpenReview failed for '{paper_name}', trying web search...")
    #         try:
    #             pdf_url = await web_search_for_paper_pdf(paper_name)
    #             if pdf_url:
    #                 async with httpx.AsyncClient() as client:
    #                     response = await client.get(pdf_url, follow_redirects=True)
    #                     if response.status_code != 200:
    #                         raise ValueError(f"HTTP {response.status_code}")
    #                     ctype = (response.headers.get("content-type") or "").lower()
    #                     is_pdf = "pdf" in ctype or pdf_url.lower().endswith(".pdf")
    #                     if not is_pdf and len(response.content) >= 5:
    #                         is_pdf = response.content[:5] == b"%PDF-"
    #                     if is_pdf:
    #                         with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
    #                             tmp.write(response.content)
    #                             path = tmp.name
    #                         logger.info(f"[Resolve PDF] PDF path resolved from web search: {path}")
    #                         return path
    #         except Exception as e:
    #             logger.warning(f"[Resolve PDF] Web search fallback failed: {e}")
    #         raise openreview_404

    # Priority 5: Paper name with OpenReview disabled — web search only
    if paper_name:
        try:
            pdf_url = await web_search_for_paper_pdf(paper_name)
            if pdf_url:
                async with httpx.AsyncClient() as client:
                    response = await client.get(pdf_url, follow_redirects=True)
                    if response.status_code != 200:
                        raise ValueError(f"HTTP {response.status_code}")
                    ctype = (response.headers.get("content-type") or "").lower()
                    is_pdf = "pdf" in ctype or pdf_url.lower().endswith(".pdf")
                    if not is_pdf and len(response.content) >= 5:
                        is_pdf = response.content[:5] == b"%PDF-"
                    if is_pdf:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                            tmp.write(response.content)
                            path = tmp.name
                        logger.info(f"[Resolve PDF] PDF path resolved from web search: {path}")
                        return path
        except Exception as e:
            logger.warning(f"[Resolve PDF] Web search for paper name failed: {e}")
        raise HTTPException(
            status_code=404,
            detail=f"No PDF found for paper '{paper_name}' via web search."
        )
    
    raise HTTPException(
        status_code=400,
        detail="No valid PDF source provided. Please provide file_ids, paper_url, or paper_name."
    )


def extract_tables(pdf_path):
    """
    Extract tables from PDF using Camelot (primary) and Tabula (fallback).
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        List of formatted table text strings
    """
    # Try Camelot first (best for vector PDFs)
    try:
        tables = camelot.read_pdf(pdf_path, pages="all")
        return [f"Table {i+1}:\n{t.df.to_string(index=False)}" 
                for i, t in enumerate(tables)]
    except Exception as e:
        logger.debug(f"[ExtractTables] Camelot failed: {e}, trying Tabula...")
    
    # Fallback to Tabula
    try:
        dfs = tabula.read_pdf(pdf_path, pages="all", multiple_tables=True)
        return [f"Table (Tabula) {i+1}:\n{df.to_string(index=False)}" 
                for i, df in enumerate(dfs)]
    except Exception as e:
        logger.warning(f"[ExtractTables] Both extraction methods failed: {e}")
        return []


def extract_figures(pdf_path, out_dir="figures"):
    """
    Extract figures from PDF and save as images.
    
    Args:
        pdf_path: Path to PDF file
        out_dir: Directory to save extracted images
        
    Returns:
        List of extracted image file paths
    """
    os.makedirs(out_dir, exist_ok=True)
    figure_paths = []
    
    with fitz.open(pdf_path) as doc:
        for page_num, page in enumerate(doc):
            images = page.get_images(full=True)
            for img_idx, img in enumerate(images):
                xref = img[0]
                pix = None
                try:
                    pix = fitz.Pixmap(doc, xref)
                    # Only process GRAY or RGB images (n < 5)
                    if pix.n < 5:
                        img_path = os.path.join(out_dir, f"p{page_num}_img{img_idx}.png")
                        pix.save(img_path)
                        figure_paths.append(img_path)
                finally:
                    if pix is not None:
                        pix = None  # Release Pixmap resource
    
    return figure_paths

def get_embedding_model():
    """Get or initialize the embedding model (lazy loading with thread safety)"""
    global _model
    # Double-checked locking pattern for thread-safe initialization
    if _model is None:
        with _model_lock:
            # Check again after acquiring lock (another thread might have loaded it)
            if _model is None:
                # Disable FP16 on Apple Silicon to prevent segmentation faults
                # FP16 support is problematic on M1/M2/M3 chips
                is_apple = platform.system() == 'Darwin' and platform.machine() == 'arm64'
                use_fp16 = not is_apple
                
                if is_apple:
                    logger.info("[Embeddings] Detected Apple Silicon - disabling FP16 for compatibility")
                
                logger.info(f"[Embeddings] Loading FlagAutoModel: BAAI/bge-base-en-v1.5 (FP16={use_fp16})...")
                try:
                    _model = FlagAutoModel.from_finetuned('BAAI/bge-base-en-v1.5',
                                                          query_instruction_for_retrieval="Represent this sentence for searching relevant passages:",
                                                          use_fp16=use_fp16)  # Normalize embeddings at model initialization
                    logger.info("[Embeddings] Model loaded successfully")
                except Exception as e:
                    logger.error(f"[Embeddings] Failed to load model: {str(e)}\n{traceback.format_exc()}")
                    # If FP16 fails even on non-Apple Silicon, retry with FP16 disabled
                    if use_fp16:
                        logger.warning("[Embeddings] FP16 failed, retrying with FP32...")
                        try:
                            _model = FlagAutoModel.from_finetuned('BAAI/bge-base-en-v1.5',
                                                                  query_instruction_for_retrieval="Represent this sentence for searching relevant passages:",
                                                                  use_fp16=False,
                                                                  normalize_embeddings=True)  # Normalize embeddings at model initialization
                            logger.info("[Embeddings] Model loaded successfully with FP32")
                        except Exception as retry_error:
                            logger.error(f"[Embeddings] Failed to load model with FP32: {str(retry_error)}\n{traceback.format_exc()}")
                            raise
                    else:
                        raise
    return _model


def embed_texts(texts, batch_size=32):
    """
    Create embeddings for a list of texts using BGE-base-en-v1.5 model.
    
    Args:
        texts: List of text strings to encode
        batch_size: Number of texts to encode per batch (smaller batches use less memory)
    
    Returns:
        numpy array of embeddings with shape (num_texts, embedding_dim)
    """
    try:
        embedding_model = get_embedding_model()
        logger.info(f"[Embeddings] Encoding {len(texts)} texts in batches of {batch_size}...")
        
        # Process in batches to avoid memory issues, especially on Apple Silicon
        # Note: normalize_embeddings is set at model initialization, not when calling encode()
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(texts) - 1) // batch_size + 1
            logger.debug(f"[Embeddings] Encoding batch {batch_num}/{total_batches} ({len(batch)} texts)...")
            
            batch_embeddings = embedding_model.encode(batch)
            
            # Ensure embeddings are numpy arrays
            if not isinstance(batch_embeddings, np.ndarray):
                batch_embeddings = np.array(batch_embeddings)
            
            all_embeddings.append(batch_embeddings)
        
        # Concatenate all batches
        result = np.vstack(all_embeddings).astype("float32")
        logger.info(f"[Embeddings] Created embeddings with shape: {result.shape}")
        return result
    except Exception as e:
        logger.error(f"[Embeddings] Failed to create embeddings: {str(e)}\n{traceback.format_exc()}")
        raise


class VectorIndex:
    """FAISS-based vector index for RAG retrieval"""
    def __init__(self, dim):
        self.index = faiss.IndexFlatIP(dim)
        self.texts = []

    def add(self, embeddings, texts):
        """Add embeddings and corresponding texts to the index"""
        self.index.add(embeddings)
        self.texts.extend(texts)

    def query(self, embedding, k=5):
        """Query the index for k nearest neighbors"""
        if len(self.texts) == 0:
            logger.warning("[VectorIndex] Query called on empty index")
            return []
        
        # Ensure k doesn't exceed the number of indexed items
        k = min(k, len(self.texts))
        scores, idxs = self.index.search(embedding.reshape(1, -1), k)
        
        # Filter out invalid indices (FAISS returns -1 for invalid results)
        valid_results = []
        for idx in idxs[0]:
            if 0 <= idx < len(self.texts):
                valid_results.append(self.texts[idx])
        
        logger.info(f"[VectorIndex] Query returned {len(valid_results)} valid results (requested k={k})")
        return valid_results





async def build_rag_index(
    pdf_path: str,
    figure_extraction_method: str = "none",
    table_extraction_method: str = "none"
):
    """
    Build RAG index following the architecture (async optimized):
    PDF → GROBID → sections → Tables (Camelot/Tabula) → Figures (image extraction)
    → Optional additional extraction (OCR or multimodal) for selected tables/figures
    → Embeddings → Vector Index
    
    Args:
        pdf_path: Path to PDF file
        figure_extraction_method: Method for additional figure content extraction
            - "none": Only use GROBID captions (default)
            - "ocr": Use Tesseract OCR to extract text from figures
            - "multimodal": Use multi-modal AI to analyze figure content
        table_extraction_method: Method for additional table content extraction
            - "none": Only use GROBID captions (default)
            - "ocr": Use OCR/Camelot/Tabula to extract table content
            - "multimodal": Use multi-modal AI to analyze table content
    
    Implements caching: if paper has been processed before, loads from cache.
    Optimizations:
    - Parallelizes GROBID, table extraction, and figure extraction
    - Parallelizes additional extraction calls
    - Caches intermediate results (GROBID, tables, figures)
    """
    logger.info(f"[BuildIndex] Starting RAG index build for PDF: {pdf_path}")
    
    # Check cache first (content-based key from first paragraph – lightweight)
    cache_key = get_content_based_cache_key(pdf_path)
    logger.info(f"[BuildIndex] Cache key: {cache_key[:16]}...")
    
    cached_index = load_cached_index(cache_key, VectorIndex)
    if cached_index is not None:
        logger.info("[BuildIndex] Using cached embeddings and index")
        return cached_index
    
    logger.info("[BuildIndex] Cache not found, building new index...")
    
    # Determine if we need table/figure extraction
    need_table_extraction = table_extraction_method != "none"
    need_figure_extraction = figure_extraction_method != "none"
    need_extraction = need_table_extraction or need_figure_extraction
    
    # Load from intermediate cache if available
    cached_sections = load_cached_grobid(cache_key)
    cached_tables = load_cached_tables(cache_key) if need_table_extraction else None
    cached_figures = load_cached_figures(cache_key) if need_figure_extraction else None
    
    async def parse_grobid():
        if cached_sections:
            logger.info("[BuildIndex] Using cached GROBID parsing")
            return cached_sections
        logger.info("[BuildIndex] Parsing PDF with GROBID...")
        try:
            sections = await asyncio.to_thread(grobid_parse, pdf_path)
            logger.info(f"[BuildIndex] GROBID parsed {len(sections.get('sections', sections) if isinstance(sections, dict) else sections)} sections")
            save_cached_grobid(cache_key, sections)
            return sections
        except Exception as e:
            logger.error(f"[BuildIndex] GROBID parsing error: {str(e)}\n{traceback.format_exc()}")
            raise
    
    async def extract_tables_async():
        if not need_table_extraction:
            return []
        if cached_tables:
            logger.info("[BuildIndex] Using cached table extraction")
            return cached_tables
        logger.info("[BuildIndex] Extracting tables...")
        try:
            tables = await asyncio.to_thread(extract_tables, pdf_path)
            logger.info(f"[BuildIndex] Extracted {len(tables)} tables")
            save_cached_tables(cache_key, tables)
            return tables
        except Exception as e:
            logger.error(f"[BuildIndex] Table extraction error: {str(e)}\n{traceback.format_exc()}")
            raise
    
    async def extract_figures_async():
        if not need_figure_extraction:
            return []
        if cached_figures:
            logger.info("[BuildIndex] Using cached figure extraction")
            return cached_figures
        logger.info("[BuildIndex] Extracting figures...")
        try:
            figure_paths = await asyncio.to_thread(extract_figures, pdf_path)
            logger.info(f"[BuildIndex] Extracted {len(figure_paths)} figures")
            save_cached_figures(cache_key, figure_paths)
            return figure_paths
        except Exception as e:
            logger.error(f"[BuildIndex] Figure extraction error: {str(e)}\n{traceback.format_exc()}")
            raise
    
    # Run operations conditionally - only extract tables/figures if needed
    if need_extraction:
        logger.info("[BuildIndex] Running GROBID parsing and extraction in parallel...")
        grobid_result, tables, figure_paths = await asyncio.gather(
            parse_grobid(),
            extract_tables_async(),
            extract_figures_async()
        )
    else:
        logger.info("[BuildIndex] Only using GROBID parsing (no table/figure extraction needed)...")
        grobid_result = await parse_grobid()
        tables = []
        figure_paths = []

    # Extract sections and captions from GROBID result
    sections = grobid_result.get("sections", grobid_result) if isinstance(grobid_result, dict) else grobid_result
    figure_captions = grobid_result.get("figure_captions", []) if isinstance(grobid_result, dict) else []
    table_captions = grobid_result.get("table_captions", []) if isinstance(grobid_result, dict) else []

    # Build initial text chunks from sections and captions
    texts = [f"[SECTION] {title}\n{text}" for title, text in sections.items()]
    texts.extend(f"[FIGURE CAPTION {i+1}]\n{caption}" for i, caption in enumerate(figure_captions))
    texts.extend(f"[TABLE CAPTION {i+1}]\n{caption}" for i, caption in enumerate(table_captions))
    
    logger.info(f"[BuildIndex] Added {len(sections)} sections, {len(figure_captions)} figure captions, {len(table_captions)} table captions")

    # Apply additional extraction only if needed
    if need_extraction:
        # Select important tables and figures based on heuristics
        logger.info("[BuildIndex] Selecting important tables and figures...")
        selected_table_indices, selected_figure_indices = select_important_tables_figures(
            sections, tables, figure_paths, max_tables=3, max_figures=3
        )
        
        # Prepare enrichment tasks
        enrichment_tasks = []
        
        # Enrich figures if needed
        if figure_extraction_method != "none" and selected_figure_indices:
            selected_figure_paths = [figure_paths[idx] for idx in selected_figure_indices]
            selected_figure_captions = [
                figure_captions[idx] if idx < len(figure_captions) else f"Figure {idx+1}" 
                for idx in selected_figure_indices
            ]
            
            logger.info(f"[BuildIndex] Applying {figure_extraction_method} to {len(selected_figure_indices)} figures...")
            if figure_extraction_method == "ocr":
                async def enrich_figures_task():
                    try:
                        enriched = await asyncio.to_thread(enrich_figures_with_ocr, selected_figure_paths, selected_figure_captions)
                        for fig_data in enriched:
                            orig_idx = selected_figure_indices[fig_data["figure_index"]]
                            if fig_data.get("content"):
                                texts.append(f"[FIGURE {orig_idx+1}] Caption: {fig_data['caption']}\nOCR Content:\n{fig_data['content']}")
                                logger.debug(f"[BuildIndex] Figure {orig_idx+1}: {len(fig_data['content'])} chars")
                    except Exception as e:
                        logger.error(f"[BuildIndex] Failed OCR extraction for figures: {str(e)}")
                enrichment_tasks.append(enrich_figures_task())
            elif figure_extraction_method == "multimodal":
                async def enrich_figures_task():
                    try:
                        enriched = await enrich_figures_with_multimodal(selected_figure_paths, selected_figure_captions)
                        for fig_data in enriched:
                            orig_idx = selected_figure_indices[fig_data["figure_index"]]
                            if fig_data.get("content"):
                                texts.append(f"[FIGURE {orig_idx+1}] Caption: {fig_data['caption']}\nAnalysis:\n{fig_data['content']}")
                                logger.debug(f"[BuildIndex] Figure {orig_idx+1}: {len(fig_data['content'])} chars")
                    except Exception as e:
                        logger.error(f"[BuildIndex] Failed multimodal extraction for figures: {str(e)}")
                enrichment_tasks.append(enrich_figures_task())
        
        # Enrich tables if needed
        if selected_table_indices:
            selected_table_content = [tables[idx] for idx in selected_table_indices]
            selected_table_captions = [
                table_captions[idx] if idx < len(table_captions) else f"Table {idx+1}" 
                for idx in selected_table_indices
            ]
            
            if table_extraction_method == "none":
                # Add basic table content
                for idx in selected_table_indices:
                    if idx < len(tables):
                        texts.append(f"[TABLE {idx+1}]\n{tables[idx]}")
            else:
                logger.info(f"[BuildIndex] Applying {table_extraction_method} to {len(selected_table_indices)} tables...")
                if table_extraction_method == "ocr":
                    async def enrich_tables_task():
                        try:
                            enriched = await asyncio.to_thread(enrich_tables_with_ocr, selected_table_content, selected_table_captions)
                            for table_data in enriched:
                                orig_idx = selected_table_indices[table_data["table_index"]]
                                if table_data.get("content"):
                                    texts.append(f"[TABLE {orig_idx+1}] Caption: {table_data['caption']}\nContent:\n{table_data['content']}")
                                    logger.debug(f"[BuildIndex] Table {orig_idx+1}: {len(table_data['content'])} chars")
                        except Exception as e:
                            logger.error(f"[BuildIndex] Failed OCR extraction for tables: {str(e)}")
                    enrichment_tasks.append(enrich_tables_task())
                elif table_extraction_method == "multimodal":
                    async def enrich_tables_task():
                        try:
                            enriched = await enrich_tables_with_multimodal(selected_table_content, selected_table_captions)
                            for table_data in enriched:
                                if table_data["table_index"] < len(selected_table_indices):
                                    orig_idx = selected_table_indices[table_data["table_index"]]
                                    analysis = table_data.get("analysis", "")
                                    if analysis:
                                        texts.append(f"[TABLE {orig_idx+1}] Caption: {table_data['caption']}\nContent:\n{table_data.get('content', '')}\nAnalysis:\n{analysis}")
                                        logger.debug(f"[BuildIndex] Table {orig_idx+1}: {len(analysis)} chars")
                        except Exception as e:
                            logger.error(f"[BuildIndex] Failed multimodal extraction for tables: {str(e)}")
                    enrichment_tasks.append(enrich_tables_task())
        
        # Apply enrichment in parallel
        if enrichment_tasks:
            await asyncio.gather(*enrichment_tasks)
    else:
        logger.info("[BuildIndex] Skipping table/figure extraction (GROBID-only mode)")

    logger.info(f"[BuildIndex] Total text chunks prepared: {len(texts)}")

    # Create embeddings (optimized batch size for faster processing)
    logger.info("[BuildIndex] Creating embeddings...")
    try:
        # Use larger batch size for faster processing if we have many texts
        # Default batch_size=32, increase to 64 for better throughput (trade-off: more memory)
        batch_size = 64 if len(texts) > 50 else 32
        embeddings = await asyncio.to_thread(embed_texts, texts, batch_size)
        logger.info(f"[BuildIndex] Embeddings created with shape: {embeddings.shape}")
    except Exception as e:
        logger.error(f"[BuildIndex] Embedding creation error: {str(e)}\n{traceback.format_exc()}")
        raise
    
    # Build vector index (RAG) - run in thread pool for async
    logger.info("[BuildIndex] Building vector index...")
    try:
        def build_index():
            index = VectorIndex(embeddings.shape[1])
            index.add(embeddings, texts)
            return index
        
        index = await asyncio.to_thread(build_index)
        logger.info(f"[BuildIndex] Vector index built successfully with {len(index.texts)} entries")
    except Exception as e:
        logger.error(f"[BuildIndex] Index building error: {str(e)}\n{traceback.format_exc()}")
        raise

    # Save to cache (run in background thread to not block)
    logger.info("[BuildIndex] Saving to cache...")
    await asyncio.to_thread(save_cached_index, cache_key, index, embeddings)

    logger.info("[BuildIndex] RAG index build completed successfully")
    return index


