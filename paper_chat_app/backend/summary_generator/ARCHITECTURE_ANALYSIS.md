# Summary Backend Architecture Analysis

## Pipeline Architecture Check

### ✅ 1. PDF → GROBID → Structured Sections
**Status**: IMPLEMENTED ✓
- Location: `utils.py` lines 63-88
- Function: `grobid_parse(pdf_path)` and `parse_tei_xml(xml_text)`
- Implementation: Uses GROBID API at `http://localhost:8070/api/processFulltextDocument`
- Output: Dictionary mapping section titles to text content

### ✅ 2. Tables → Camelot / Tabula (text-first)
**Status**: IMPLEMENTED ✓
- Location: `utils.py` lines 5-24
- Function: `extract_tables(pdf_path)`
- Implementation: 
  - Primary: Camelot (line 10) for vector PDFs
  - Fallback: Tabula (line 18) if Camelot fails
- Output: List of table text strings

### ⚠️ 3. Figures → Extracted Images
**Status**: PARTIALLY IMPLEMENTED
- Location: `utils.py` lines 32-55
- Function: `extract_figures_text(pdf_path, out_dir="figures")`
- Issues:
  - Function name mismatch: called `extract_figures_text` but `embeddings.py` expects `extract_figures`
  - Returns OCR text, not image paths needed for multimodal analysis
  - Needs to return image paths for `analyze_figure()` which expects image_path

### ✅ 4. Multimodal GPT → Figure & Table Understanding
**Status**: IMPLEMENTED ✓
- Location: `analyzer.py`
- Functions:
  - `analyze_figure(image_path)`: Lines 13-29, uses GPT-4.1 with vision API
  - `analyze_table(csv_text)`: Lines 32-53, uses GPT-4.1 for text analysis
- Implementation: Both use OpenAI GPT-4.1 with appropriate prompts

### ✅ 5. Embeddings → Vector Index (RAG)
**Status**: IMPLEMENTED ✓
- Location: `embeddings.py` lines 12-31
- Functions:
  - `embed_texts(texts)`: Uses OpenAI text-embedding-3-large model
  - `VectorIndex` class: Uses FAISS IndexFlatIP for similarity search
- Implementation: Creates embeddings and builds vector index

### ✅ 6. Query-driven Retrieval
**Status**: IMPLEMENTED ✓
- Location: `main.py` lines 61-63
- Function: `synthesize_answer()` queries the index
- Implementation: Uses vector similarity search with k=8 nearest neighbors

### ✅ 7. Final Synthesis
**Status**: IMPLEMENTED ✓
- Location: `main.py` lines 65-87
- Function: `synthesize_answer()` uses GPT model to synthesize answer
- Implementation: Uses retrieved content to generate comprehensive summary

## Critical Issues Found

### 1. Import Errors (CRITICAL)
- `embeddings.py` has circular imports and wrong module names:
  - Line 4: `from grobid import grobid_parse` → should be `from .utils import grobid_parse`
  - Line 5: `from tables import extract_tables` → should be `from .utils import extract_tables`
  - Line 6: `from figures import extract_figures` → should be `from .utils import extract_figures_text`
  - Line 7: `from vision import analyze_figure, analyze_table` → should be `from .analyzer import analyze_figure, analyze_table`
  - Line 8: `from embeddings import embed_texts, VectorIndex` → CIRCULAR IMPORT! (should be removed, functions are defined in same file)

- `main.py` has wrong imports:
  - Line 10: `from pdf_parser import ...` → should be `from .utils import grobid_parse, parse_tei_xml`
  - Line 11: `from table_retrieval import extract_tables` → should be `from .utils import extract_tables`
  - Line 12: `from image_retrieval import extract_figures_text` → should be `from .utils import extract_figures_text`
  - Line 13: `from section_summary import ...` → these modules don't exist
  - Line 18: `from sythesize import synthesize_answer` → typo, and `synthesize_answer` is defined in same file
  - Line 17: `from embeddings import embed_texts` → should be `from .embeddings import embed_texts`

### 2. Data Structure Mismatches (CRITICAL)
- `build_rag_index()` line 46: `table["data"]` → but `extract_tables()` returns list of strings, not dicts
- `build_rag_index()` line 38: calls `extract_figures()` → but function is named `extract_figures_text()` in utils.py
- `build_rag_index()` line 49: `analyze_figure(fig)` → expects image_path, but `extract_figures_text()` returns text

### 3. Missing PDF Path Resolution (CRITICAL)
- `main.py` line 45: `build_rag_index(pdf_path)` → `pdf_path` is undefined
- Need to extract PDF path from request (file_ids, paper_url, or paper_name)

### 4. Figure Extraction Needs Refactoring
- Current: `extract_figures_text()` does OCR and returns text
- Needed: Function that returns image paths for multimodal analysis
- Should have: `extract_figures()` that returns image paths AND optionally does OCR

### 5. Table Data Structure Inconsistency
- `extract_tables()` returns: `List[str]` (table text strings)
- `analyze_table()` expects: `csv_text` (string) ✓ (this is actually OK)
- But `build_rag_index()` tries to access `table["data"]` which doesn't exist

## Summary

**Architecture Compliance**: 6/7 stages properly implemented (Figures extraction needs adjustment)
**Code Quality**: Multiple import errors and data structure mismatches prevent execution
**Action Required**: Fix imports, resolve PDF path, refactor figure extraction, fix data structures
