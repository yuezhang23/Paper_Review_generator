"""
Content extraction utilities for processing files and text.
All functions in this module do not require API calls.
"""

import io
from typing import Optional, List, Dict, Any
from difflib import SequenceMatcher
import PyPDF2


def extract_text_from_pdf(file_content: bytes) -> str:
    """Extract text from PDF file"""
    try:
        pdf_file = io.BytesIO(file_content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        return f"Error extracting text from PDF: {str(e)}"


def extract_text_from_file(file_content: bytes, filename: str) -> str:
    """Extract text from various file types"""
    if filename.lower().endswith('.pdf'):
        return extract_text_from_pdf(file_content)
    elif filename.lower().endswith('.txt'):
        try:
            return file_content.decode('utf-8')
        except:
            return file_content.decode('utf-8', errors='ignore')
    else:
        return f"File type not supported for text extraction: {filename}"


def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity between two texts using SequenceMatcher"""
    return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()


def find_best_matching_paper(query: str, search_results: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Find the best matching paper from Google PSE search results based on query similarity.
    
    Args:
        query: User's search query
        search_results: List of Google PSE search results
        
    Returns:
        Best matching paper dictionary or None
    """
    if not search_results:
        return None

    query_lower = query.lower()
    query_words = set(query_lower.split())
    
    best_match = None
    best_score = 0.0
    
    for result in search_results:
        title = result.get('title', '').lower()
        snippet = result.get('snippet', '').lower()
        combined_text = f"{title} {snippet}"
        
        # Calculate multiple similarity metrics
        # 1. Title similarity
        title_similarity = calculate_similarity(query, title)
        
        # 2. Keyword overlap
        combined_words = set(combined_text.split())
        keyword_overlap = len(query_words.intersection(combined_words)) / max(len(query_words), 1)
        
        # 3. Combined text similarity
        text_similarity = calculate_similarity(query, combined_text)
        
        # Weighted score: title is most important, then keyword overlap, then text similarity
        score = (title_similarity * 0.5) + (keyword_overlap * 0.3) + (text_similarity * 0.2)
        
        # Bonus for academic domains
        if any(domain in result.get('link', '').lower() for domain in ['arxiv', 'openreview', 'edu', 'acm', 'ieee']):
            score *= 1.2
        
        if score > best_score:
            best_score = score
            best_match = result
    
    return best_match


def extract_augmented_prompt_from_messages(messages: List[Dict[str, Any]]) -> str:
    """Extract the augmented part of the prompt (system messages with paper context)"""
    augmented_parts = []
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            # Only include paper-related context, not the base system prompt
            if "OPENREVIEW PAPERS" in content or "RETRIEVED PAPERS" in content or "BEST MATCHING PAPER" in content or "UPLOADED FILES" in content or "GOOGLE PSE" in content:
                augmented_parts.append(content)
    return "\n\n".join(augmented_parts)
