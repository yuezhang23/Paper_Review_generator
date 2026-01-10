import os
import faiss
import numpy as np
import logging
import traceback
import platform
import hashlib
import pickle
import json
import asyncio
from typing import List, Tuple, Optional
from FlagEmbedding import FlagAutoModel
from .utils import grobid_parse, extract_tables, extract_figures
from .analyzer import analyze_figure, analyze_table

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

# Cache directory for embeddings
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "embeddings_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def is_apple_silicon():
    """Detect if running on Apple Silicon (M1/M2/M3)"""
    # Check for Apple Silicon architecture
    # arm64 on macOS indicates Apple Silicon
    return platform.system() == 'Darwin' and platform.machine() == 'arm64'

def get_embedding_model():
    """Get or initialize the embedding model (lazy loading)"""
    global _model
    if _model is None:
        # Disable FP16 on Apple Silicon to prevent segmentation faults
        # FP16 support is problematic on M1/M2/M3 chips
        use_fp16 = not is_apple_silicon()
        
        if is_apple_silicon():
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


def get_pdf_hash(pdf_path: str) -> str:
    """Generate a hash for the PDF file to use as cache key"""
    hash_md5 = hashlib.md5()
    with open(pdf_path, "rb") as f:
        # Read file in chunks to handle large files
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def load_cached_grobid(pdf_hash: str) -> Optional[dict]:
    """Load cached GROBID parsing results"""
    cache_file = os.path.join(CACHE_DIR, f"{pdf_hash}_grobid.json")
    if not os.path.exists(cache_file):
        return None
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[Cache] Failed to load cached GROBID: {str(e)}")
        return None


def save_cached_grobid(pdf_hash: str, sections: dict):
    """Save GROBID parsing results to cache"""
    try:
        cache_file = os.path.join(CACHE_DIR, f"{pdf_hash}_grobid.json")
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(sections, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[Cache] Failed to save GROBID cache: {str(e)}")


def load_cached_tables(pdf_hash: str) -> Optional[List[str]]:
    """Load cached table extraction results"""
    cache_file = os.path.join(CACHE_DIR, f"{pdf_hash}_tables.json")
    if not os.path.exists(cache_file):
        return None
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[Cache] Failed to load cached tables: {str(e)}")
        return None


def save_cached_tables(pdf_hash: str, tables: List[str]):
    """Save table extraction results to cache"""
    try:
        cache_file = os.path.join(CACHE_DIR, f"{pdf_hash}_tables.json")
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(tables, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[Cache] Failed to save tables cache: {str(e)}")


def load_cached_figures(pdf_hash: str) -> Optional[List[str]]:
    """Load cached figure paths"""
    cache_file = os.path.join(CACHE_DIR, f"{pdf_hash}_figures.json")
    if not os.path.exists(cache_file):
        return None
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            figure_paths = json.load(f)
            # Verify that figure files still exist
            existing_paths = [p for p in figure_paths if os.path.exists(p)]
            if len(existing_paths) != len(figure_paths):
                logger.warning(f"[Cache] Some cached figure files are missing, will re-extract")
                return None
            return existing_paths
    except Exception as e:
        logger.warning(f"[Cache] Failed to load cached figures: {str(e)}")
        return None


def save_cached_figures(pdf_hash: str, figure_paths: List[str]):
    """Save figure paths to cache"""
    try:
        cache_file = os.path.join(CACHE_DIR, f"{pdf_hash}_figures.json")
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(figure_paths, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[Cache] Failed to save figures cache: {str(e)}")


def load_cached_index(pdf_hash: str) -> Optional[VectorIndex]:
    """Load cached embeddings and index if available"""
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


def save_cached_index(pdf_hash: str, index: VectorIndex, embeddings: np.ndarray):
    """Save embeddings and index to cache"""
    try:
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
    
    Returns:
        Tuple of (selected_table_indices, selected_figure_indices)
    """
    selected_tables = []
    selected_figures = []
    
    # Handle empty tables/figures
    if not tables and not figure_paths:
        logger.info("[Selection] No tables or figures to select")
        return [], []
    
    # Get Abstract and Conclusion sections
    abstract_text = sections.get("Abstract", "").lower()
    conclusion_text = sections.get("Conclusion", "").lower()
    
    # Check all sections for "main results" mentions
    main_results_sections = []
    for section_title, section_text in sections.items():
        if "main result" in section_title.lower() or "main result" in section_text.lower():
            main_results_sections.append(section_text.lower())
    
    all_relevant_text = abstract_text + " " + conclusion_text + " " + " ".join(main_results_sections)
    
    # Keywords for SOTA/ablation comparisons
    sota_keywords = ["sota", "state-of-the-art", "state of the art", "best result", "competitive", "superior"]
    ablation_keywords = ["ablation", "ablate", "ablation study", "ablation analysis"]
    
    # Score tables
    table_scores = []
    if tables:
        for i, table_text in enumerate(tables):
        score = 0
        table_lower = table_text.lower()
        
        # Check if table number is mentioned in abstract/conclusion
        table_refs = [f"table {i+1}", f"table{i+1}", f"tab. {i+1}", f"tab.{i+1}"]
        for ref in table_refs:
            if ref in all_relevant_text:
                score += 10
                logger.info(f"[Selection] Table {i+1} mentioned in Abstract/Conclusion/Main Results")
        
        # Check for SOTA comparisons
        for keyword in sota_keywords:
            if keyword in table_lower:
                score += 5
                logger.info(f"[Selection] Table {i+1} contains SOTA comparison")
        
        # Check for ablations
        for keyword in ablation_keywords:
            if keyword in table_lower:
                score += 5
                logger.info(f"[Selection] Table {i+1} contains ablation study")
        
        # Check if labeled as main results
        if "main result" in table_lower:
            score += 8
            logger.info(f"[Selection] Table {i+1} labeled as main results")
        
            table_scores.append((score, i))
    
    # Select top tables
    if table_scores:
        table_scores.sort(reverse=True, key=lambda x: x[0])
        selected_tables = [idx for score, idx in table_scores[:max_tables] if score > 0]
        if not selected_tables:
            # If no tables meet criteria, select first few
            selected_tables = list(range(min(max_tables, len(tables))))
            logger.info(f"[Selection] No tables met selection criteria, selecting first {len(selected_tables)} tables")
        else:
            logger.info(f"[Selection] Selected {len(selected_tables)} important tables: {selected_tables}")
    else:
        logger.info("[Selection] No tables available for selection")
    
    # Score figures (using figure paths as reference - figures are numbered by extraction order)
    figure_scores = []
    if figure_paths:
        for i, fig_path in enumerate(figure_paths):
        score = 0
        
        # Check if figure number is mentioned in abstract/conclusion
        # Figure references typically use "Figure X" or "Fig. X"
        fig_refs = [f"figure {i+1}", f"figure{i+1}", f"fig. {i+1}", f"fig.{i+1}", f"fig {i+1}"]
        for ref in fig_refs:
            if ref in all_relevant_text:
                score += 10
                logger.info(f"[Selection] Figure {i+1} mentioned in Abstract/Conclusion/Main Results")
        
        # For figures, we can't easily check content, so we rely on mentions
        # But we'll also check if it's one of the first few figures (often important)
        if i < 3:  # First 3 figures are often important
            score += 2
        
            figure_scores.append((score, i))
    
    # Select top figures
    if figure_scores:
        figure_scores.sort(reverse=True, key=lambda x: x[0])
        selected_figures = [idx for score, idx in figure_scores[:max_figures] if score > 0]
        if not selected_figures:
            # If no figures meet criteria, select first few
            selected_figures = list(range(min(max_figures, len(figure_paths))))
            logger.info(f"[Selection] No figures met selection criteria, selecting first {len(selected_figures)} figures")
        else:
            logger.info(f"[Selection] Selected {len(selected_figures)} important figures: {selected_figures}")
    else:
        logger.info("[Selection] No figures available for selection")
    
    return selected_tables, selected_figures


async def build_rag_index(pdf_path):
    """
    Build RAG index following the architecture (async optimized):
    PDF → GROBID → sections → Tables (Camelot/Tabula) → Figures (image extraction)
    → Optional Multimodal GPT analysis (selected tables/figures only, max 3 each, parallelized)
    → Embeddings → Vector Index
    
    Implements caching: if paper has been processed before, loads from cache.
    Optimizations:
    - Parallelizes GROBID, table extraction, and figure extraction
    - Parallelizes multimodal GPT analysis calls
    - Caches intermediate results (GROBID, tables, figures)
    """
    logger.info(f"[BuildIndex] Starting RAG index build for PDF: {pdf_path}")
    
    # Check cache first
    pdf_hash = get_pdf_hash(pdf_path)
    logger.info(f"[BuildIndex] PDF hash: {pdf_hash[:16]}...")
    
    cached_index = load_cached_index(pdf_hash)
    if cached_index is not None:
        logger.info("[BuildIndex] Using cached embeddings and index")
        return cached_index
    
    logger.info("[BuildIndex] Cache not found, building new index...")
    
    # Parallelize Step 1-3: GROBID parsing, table extraction, and figure extraction (independent operations)
    logger.info("[BuildIndex] Step 1-3: Parallelizing GROBID parsing, table extraction, and figure extraction...")
    
    # Load from intermediate cache if available
    cached_sections = load_cached_grobid(pdf_hash)
    cached_tables = load_cached_tables(pdf_hash)
    cached_figures = load_cached_figures(pdf_hash)
    
    async def parse_grobid():
        if cached_sections:
            logger.info("[BuildIndex] Using cached GROBID parsing")
            return cached_sections
        logger.info("[BuildIndex] Step 1: Parsing PDF with GROBID...")
        try:
            sections = await asyncio.to_thread(grobid_parse, pdf_path)
            logger.info(f"[BuildIndex] GROBID parsed {len(sections)} sections: {list(sections.keys())}")
            save_cached_grobid(pdf_hash, sections)
            return sections
        except Exception as e:
            logger.error(f"[BuildIndex] Step 1 failed - GROBID parsing error: {str(e)}\n{traceback.format_exc()}")
            raise
    
    async def extract_tables_async():
        if cached_tables:
            logger.info("[BuildIndex] Using cached table extraction")
            return cached_tables
        logger.info("[BuildIndex] Step 2: Extracting tables...")
        try:
            tables = await asyncio.to_thread(extract_tables, pdf_path)
            logger.info(f"[BuildIndex] Extracted {len(tables)} tables")
            save_cached_tables(pdf_hash, tables)
            return tables
        except Exception as e:
            logger.error(f"[BuildIndex] Step 2 failed - Table extraction error: {str(e)}\n{traceback.format_exc()}")
            raise
    
    async def extract_figures_async():
        if cached_figures:
            logger.info("[BuildIndex] Using cached figure extraction")
            return cached_figures
        logger.info("[BuildIndex] Step 3: Extracting figures...")
        try:
            figure_paths = await asyncio.to_thread(extract_figures, pdf_path)
            logger.info(f"[BuildIndex] Extracted {len(figure_paths)} figures: {figure_paths}")
            save_cached_figures(pdf_hash, figure_paths)
            return figure_paths
        except Exception as e:
            logger.error(f"[BuildIndex] Step 3 failed - Figure extraction error: {str(e)}\n{traceback.format_exc()}")
            raise
    
    # Run all three operations in parallel
    sections, tables, figure_paths = await asyncio.gather(
        parse_grobid(),
        extract_tables_async(),
        extract_figures_async()
    )

    texts = []

    # Add sections to texts
    logger.info("[BuildIndex] Adding sections to texts...")
    for title, text in sections.items():
        texts.append(f"[SECTION] {title}\n{text}")
    logger.info(f"[BuildIndex] Added {len(sections)} sections to texts list")

    # Step 4: Select important tables and figures based on heuristics
    logger.info("[BuildIndex] Step 4: Selecting important tables and figures...")
    selected_table_indices, selected_figure_indices = select_important_tables_figures(
        sections, tables, figure_paths, max_tables=3, max_figures=3
    )
    
    # Step 4: Analyze selected tables and figures with multimodal GPT in parallel (optional, max 3 each)
    analysis_tasks = []
    analysis_metadata = []  # Track (type, idx)
    
    # Create tasks for table analysis
    if selected_table_indices:
        logger.info(f"[BuildIndex] Step 4a: Preparing to analyze {len(selected_table_indices)} selected tables with AI (parallel)...")
        for idx in selected_table_indices:
            task = analyze_table(tables[idx])
            analysis_tasks.append(task)
            analysis_metadata.append(("table", idx))
    else:
        logger.info("[BuildIndex] Step 4a: No tables selected for multimodal analysis")
    
    # Create tasks for figure analysis
    if selected_figure_indices:
        logger.info(f"[BuildIndex] Step 4b: Preparing to analyze {len(selected_figure_indices)} selected figures with AI (parallel)...")
        for idx in selected_figure_indices:
            fig_path = figure_paths[idx]
            task = analyze_figure(fig_path)
            analysis_tasks.append(task)
            analysis_metadata.append(("figure", idx))
    else:
        logger.info("[BuildIndex] Step 4b: No figures selected for multimodal analysis")
    
    # Execute all analyses in parallel
    if analysis_tasks:
        logger.info(f"[BuildIndex] Running {len(analysis_tasks)} multimodal analyses in parallel...")
        results = await asyncio.gather(*analysis_tasks, return_exceptions=True)
        
        # Process results
        for (item_type, idx), result in zip(analysis_metadata, results):
            try:
                if isinstance(result, Exception):
                    raise result
                
                if item_type == "table":
                    texts.append(f"[TABLE {idx+1}]\n{result}")
                    logger.info(f"[BuildIndex] Table {idx+1} analyzed successfully")
                else:  # figure
                    texts.append(f"[FIGURE {idx+1}]\n{result}")
                    logger.info(f"[BuildIndex] Figure {idx+1} analyzed successfully")
            except Exception as e:
                logger.error(f"[BuildIndex] Failed to analyze {item_type} {idx+1}: {str(e)}\n{traceback.format_exc()}")
                error_text = f"[{item_type.upper()} {idx+1}]\nError analyzing {item_type}: {str(e)}"
                texts.append(error_text)

    logger.info(f"[BuildIndex] Total text chunks prepared: {len(texts)}")

    # Step 5: Create embeddings (optimized batch size for faster processing)
    logger.info("[BuildIndex] Step 5: Creating embeddings...")
    try:
        # Use larger batch size for faster processing if we have many texts
        # Default batch_size=32, increase to 64 for better throughput (trade-off: more memory)
        batch_size = 64 if len(texts) > 50 else 32
        embeddings = await asyncio.to_thread(embed_texts, texts, batch_size)
        logger.info(f"[BuildIndex] Embeddings created with shape: {embeddings.shape}")
    except Exception as e:
        logger.error(f"[BuildIndex] Step 5 failed - Embedding creation error: {str(e)}\n{traceback.format_exc()}")
        raise
    
    # Step 6: Build vector index (RAG) - run in thread pool for async
    logger.info("[BuildIndex] Step 6: Building vector index...")
    try:
        def build_index():
            index = VectorIndex(embeddings.shape[1])
            index.add(embeddings, texts)
            return index
        
        index = await asyncio.to_thread(build_index)
        logger.info(f"[BuildIndex] Vector index built successfully with {len(index.texts)} entries")
    except Exception as e:
        logger.error(f"[BuildIndex] Step 6 failed - Index building error: {str(e)}\n{traceback.format_exc()}")
        raise

    # Step 7: Save to cache (run in background thread to not block)
    logger.info("[BuildIndex] Step 7: Saving to cache...")
    await asyncio.to_thread(save_cached_index, pdf_hash, index, embeddings)

    logger.info("[BuildIndex] RAG index build completed successfully")
    return index


