"""
Summary logging utilities for paper analysis.
Handles extraction and logging of paper summaries to CSV.
"""

from typing import List, Dict, Any, Optional
from content_extraction import extract_augmented_prompt_from_messages
from utils import log_paper_summary


def log_paper_summary_if_needed(
    is_summary: bool,
    downloaded_papers: Optional[List[Dict[str, Any]]],
    openreview_papers: Optional[List[Dict[str, Any]]],
    best_matching_paper: Optional[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    analysis_response: str
) -> None:
    """
    Log paper summary if this is a summary query and we have paper context.
    
    Args:
        is_summary: Whether this is a summary query
        downloaded_papers: List of downloaded papers (if any)
        openreview_papers: List of OpenReview papers (if any)
        best_matching_paper: Best matching paper from web search (if any)
        messages: List of message dictionaries for extracting augmented prompt
        analysis_response: The analysis response from the LLM
    """
    if not is_summary or not (downloaded_papers or openreview_papers or best_matching_paper):
        return
    
    # Get paper metadata
    paper_metadata = {}
    if downloaded_papers:
        paper = downloaded_papers[0]  # Use first paper
        paper_metadata = {
            'paper_id': paper.get('paper_id', ''),
            'title': paper.get('title', ''),
            'authors': paper.get('authors', []),
            'venue': paper.get('venue', ''),
            'year': paper.get('year')
        }
    elif openreview_papers:
        paper = openreview_papers[0]
        paper_metadata = {
            'paper_id': paper.get('id', ''),
            'title': paper.get('title', ''),
            'authors': paper.get('authors', []),
            'venue': paper.get('venue', ''),
            'year': paper.get('year')
        }
    elif best_matching_paper:
        paper_metadata = {
            'title': best_matching_paper.get('title', ''),
            'url': best_matching_paper.get('link') or best_matching_paper.get('url', ''),
            'source': 'web_search'
        }
    
    # Extract augmented prompt (paper context parts)
    augmented_prompt = extract_augmented_prompt_from_messages(messages)
    
    # Log to CSV
    if paper_metadata:
        log_paper_summary(paper_metadata, augmented_prompt, analysis_response)
