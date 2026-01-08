"""
Utility module containing constants and helper functions for the paper analysis chat application.
"""

import os
import json
import csv
from typing import Dict, Any

# File storage directory
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Summary logs directory
SUMMARY_LOGS_DIR = "summary_logs"
os.makedirs(SUMMARY_LOGS_DIR, exist_ok=True)
SUMMARY_CSV_PATH = os.path.join(SUMMARY_LOGS_DIR, "paper_summaries.csv")

# Prompts directory
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

# In-memory file storage (for demo - use proper storage in production)
file_storage: Dict[str, Dict[str, Any]] = {}

def load_prompt_template(filename: str) -> str:
    """Load a prompt template from a markdown file"""
    try:
        filepath = os.path.join(PROMPTS_DIR, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            # Skip the first line if it's a markdown header (# Title)
            content = f.read()
            lines = content.split('\n')
            # Remove markdown header if present
            if lines[0].startswith('#'):
                content = '\n'.join(lines[1:]).strip()
            return content
    except Exception as e:
        print(f"Error loading prompt template {filename}: {str(e)}")
        return ""

def log_paper_summary(paper_metadata: Dict[str, Any], augmented_prompt: str, analysis: str):
    """Log paper summary to CSV file with 3 columns: paper_metadata, augmented_prompt, analysis"""
    try:
        # Check if CSV file exists, if not create with headers
        file_exists = os.path.exists(SUMMARY_CSV_PATH)
        
        with open(SUMMARY_CSV_PATH, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['paper_metadata', 'augmented_prompt', 'analysis']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            
            if not file_exists:
                writer.writeheader()
            
            # Prepare metadata as JSON string
            metadata_json = json.dumps(paper_metadata, ensure_ascii=False)
            
            # Python's csv module will automatically handle escaping quotes and newlines
            writer.writerow({
                'paper_metadata': metadata_json,
                'augmented_prompt': augmented_prompt,
                'analysis': analysis
            })
        
        print(f"[Summary Log] Saved paper summary to {SUMMARY_CSV_PATH}")
    except Exception as e:
        print(f"[Summary Log] Error saving summary: {str(e)}")

# Load prompt templates
PAPER_ANALYSIS_SYSTEM_PROMPT = load_prompt_template("paper_analysis_system_prompt.md")
PAPER_SUMMARY_TEMPLATE = load_prompt_template("paper_summary_template.md")
PLAGIARISM_ANALYSIS_TEMPLATE = load_prompt_template("plagiarism_analysis_template.md")

# Rating scores for paper evaluation
RATING_SCORES = {
    1: "Very Strong Reject: For instance, a paper with incorrect statements, improper (e.g., offensive) language, unaddressed ethical considerations, incorrect results and/or flawed methodology (e.g., training using a test set).",
    2: "Strong Reject: For instance, a paper with major technical flaws, and/or poor evaluation, limited impact, poor reproducibility and mostly unaddressed ethical considerations.",
    3: "reject, not good enough",
    4: "Borderline reject: Technically solid paper where reasons to reject, e.g., limited evaluation, outweigh reasons to accept, e.g., good evaluation. Please use sparingly.",
    5: "marginally below the acceptance threshold",
    6: "marginally above the acceptance threshold",
    7: "Accept: Technically solid paper, with high impact on at least one sub-area, or moderate-to-high impact on more than one areas, with good-to-excellent evaluation, resources, reproducibility, and no unaddressed ethical considerations.",
    8: "accept, good paper",
    9: "Very Strong Accept: Technically flawless paper with groundbreaking impact on at least one area of AI/ML and excellent impact on multiple areas of AI/ML, with flawless evaluation, resources, and reproducibility, and no unaddressed ethical considerations.",
    10: "strong accept, should be highlighted at the conference"
}

# Paper-related query suggestions
PAPER_QUERY_SUGGESTIONS = [
    "Summarize the main contributions of this paper",
    "What is the methodology used in this paper?",
    "Explain the experimental results",
    "What are the limitations of this work?",
    "Compare this paper with similar works",
    "What datasets were used?",
    "What are the key findings?",
    "Explain the technical approach in simple terms",
    "What future work is suggested?",
    "Who are the authors and their affiliations?"
]

def format_search_results_for_context(search_results: Dict[str, Any]) -> str:
    """
    Format AI Builder search results as text context for LLM.
    Replaces format_search_results_for_context from google_pse_service.
    
    Args:
        search_results: Dictionary from web_search_paper()
        
    Returns:
        Formatted string with search results
    """
    if "error" in search_results or not search_results.get("results"):
        return ""
    
    results = search_results["results"]
    if not results:
        return ""
    
    context_parts = ["=== REAL-TIME WEB SEARCH RESULTS ===\n"]
    
    for i, result in enumerate(results, 1):
        title = result.get("title", "No title")
        link = result.get("link") or result.get("url", "")
        snippet = result.get("snippet") or result.get("content", "")
        display_link = result.get("display_link", "")
        
        context_parts.append(f"Result {i}:")
        context_parts.append(f"Title: {title}")
        context_parts.append(f"URL: {link}")
        if display_link:
            context_parts.append(f"Source: {display_link}")
        if snippet:
            context_parts.append(f"Summary: {snippet}")
        context_parts.append("")
    
    context_parts.append("Use the information from these search results to provide accurate, up-to-date answers. Cite sources when referencing specific information.\n")
    
    return "\n".join(context_parts)
