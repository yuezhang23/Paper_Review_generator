"""
Utility module containing constants and helper functions for the paper analysis chat application.
"""

import os
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

# Load prompt templates
PAPER_ANALYSIS_SYSTEM_PROMPT = load_prompt_template("paper_analysis_system_prompt.md")
PAPER_SUMMARY_TEMPLATE = load_prompt_template("paper_summary_template.md")

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
