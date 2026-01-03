# Search Flow Design Documentation

## Overview

This document describes the redesigned search flow that integrates OpenReview API and Google PSE search according to the specified requirements.

## Search Flow Logic

### Step 1: OpenReview Search (If Enabled)

**Condition**: `use_openreview == True` AND `model != "supermind-agent-v1"`

1. **Search via OpenReview API first**
   - Parse query for OpenReview paper IDs, URLs, or titles
   - Fetch papers by IDs/URLs if found
   - Search by titles if found
   - If no IDs/titles, perform general OpenReview search

2. **Handle Results**:
   - If **multiple papers found**: Request user selection (including "none" option)
   - If **single paper found**: Automatically download and use it
   - If **no papers found**: Proceed to Google PSE search
   - If **user selects "none"**: Proceed to Google PSE search

### Step 2: Google PSE Search (Fallback)

**Condition**: Use Google PSE if ANY of the following is true:
- `use_openreview == False` (OpenReview is toggled off), OR
- `len(downloaded_papers) == 0 AND len(openreview_papers) == 0` (OpenReview returned no papers), OR
- `selected_paper_id == 'none'` (User selected "none" option)

**Process**:
1. Perform Google PSE search with academic focus
2. Find the **best matching paper** using similarity scoring:
   - Title similarity (50% weight)
   - Keyword overlap (30% weight)
   - Text similarity (20% weight)
   - Bonus for academic domains (arxiv, openreview, edu, acm, ieee)
3. Add best matching paper to LLM context
4. Include all search results in response metadata

### Step 3: Document Links Attachment

**Always attach document links** if:
- OpenReview API was used (has results)
- Google PSE was used (has results)

**Link Format**:
```json
{
  "document_links": [
    {
      "title": "Paper Title",
      "url": "https://openreview.net/pdf?id=...",
      "review_url": "https://openreview.net/forum?id=...",
      "source": "openreview"
    },
    {
      "title": "Best Match Paper",
      "url": "https://example.com/paper",
      "snippet": "Paper summary...",
      "source": "google_pse",
      "is_best_match": true
    }
  ]
}
```

## Flow Diagram

```
User Query
    |
    v
[OpenReview Toggled On?]
    |
    +-- Yes --> [Search OpenReview API]
    |              |
    |              +-- Papers Found? --> [Multiple?] --> [Request User Selection]
    |              |                        |
    |              |                        +-- Single --> [Auto-download & Use]
    |              |                        |
    |              |                        +-- None --> [Proceed to Google PSE]
    |              |
    |              +-- User Selected "none"? --> [Proceed to Google PSE]
    |              |
    |              +-- No Papers Found --> [Proceed to Google PSE]
    |
    +-- No --> [Proceed to Google PSE]
                |
                v
        [Google PSE Search]
                |
                v
        [Find Best Matching Paper]
                |
                v
        [Add to LLM Context]
                |
                v
        [Generate Response with Document Links]
```

## Implementation Details

### Key Functions

1. **`find_best_matching_paper(query, search_results)`**
   - Calculates similarity scores for each result
   - Returns the paper with highest score
   - Uses weighted scoring: title (50%), keywords (30%), text (20%)

2. **Similarity Calculation**
   - Uses `SequenceMatcher` for text similarity
   - Keyword overlap based on word sets
   - Academic domain bonus (1.2x multiplier)

3. **Document Links Collection**
   - OpenReview links: PDF URL and review forum URL
   - Google PSE links: Best match + top 5 results
   - All links include source attribution

## Response Format

```json
{
  "message": "AI response text...",
  "model": "grok-4-fast",
  "usage": {...},
  "pdf_links": [...],  // OpenReview PDF links (legacy format)
  "document_links": [  // All document links (new format)
    {
      "title": "...",
      "url": "...",
      "source": "openreview" | "google_pse",
      "is_best_match": true/false,
      "review_url": "...",  // Only for OpenReview
      "snippet": "..."      // Only for Google PSE
    }
  ],
  "search_results": {  // Google PSE metadata
    "source": "google_pse",
    "count": 10,
    "best_match": {
      "title": "...",
      "url": "...",
      "snippet": "..."
    }
  }
}
```

## Testing Scenarios

### Scenario 1: OpenReview Enabled, Papers Found
- Input: `use_openreview=True`, query contains OpenReview paper ID
- Expected: Use OpenReview papers, skip Google PSE
- Links: OpenReview PDF and review links

### Scenario 2: OpenReview Enabled, No Papers Found
- Input: `use_openreview=True`, no OpenReview results
- Expected: Fallback to Google PSE, find best match
- Links: Google PSE links (best match + top results)

### Scenario 3: OpenReview Enabled, User Selects "None"
- Input: `use_openreview=True`, user selects "none"
- Expected: Skip OpenReview, use Google PSE
- Links: Google PSE links only

### Scenario 4: OpenReview Disabled
- Input: `use_openreview=False`
- Expected: Direct to Google PSE search
- Links: Google PSE links only

### Scenario 5: Supermind Agent Model
- Input: `model="supermind-agent-v1"`
- Expected: Skip both OpenReview and Google PSE (uses built-in Tavily)
- Links: None (handled by model)

## Notes

- Google PSE search is **always performed** when conditions are met (no `is_search_needed()` check in fallback mode)
- Best matching paper is **automatically selected** and added to context
- Document links are **always attached** when search sources are used
- OpenReview takes **priority** when enabled and has results
- User selection is **required** only when multiple OpenReview papers are found
