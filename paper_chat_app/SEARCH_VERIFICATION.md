# Search Flow Verification

## ✅ Design Requirements Verification

### Requirement 1: OpenReview Search First
**Status**: ✅ **IMPLEMENTED**

- **Location**: Lines 654-882 in `main.py`
- **Logic**: If `use_openreview == True` and model is not `supermind-agent-v1`, search OpenReview API first
- **Implementation**:
  - Parses query for OpenReview paper IDs, URLs, or titles
  - Fetches papers by IDs/URLs
  - Searches by titles
  - Performs general OpenReview search if no IDs/titles found
  - Handles user selection for multiple papers
  - Auto-downloads single paper

### Requirement 2: Google PSE Fallback
**Status**: ✅ **IMPLEMENTED**

- **Location**: Lines 895-930 in `main.py`
- **Logic**: Use Google PSE if:
  1. OpenReview is toggled off (`not request.use_openreview`), OR
  2. OpenReview returned no papers (`not openreview_has_results`), OR
  3. User selected "none" option (`user_selected_none`)
- **Implementation**:
  - Condition check: Line 903-907
  - Google PSE search: Lines 912-930
  - Always performs search (no `is_search_needed()` check in fallback mode)

### Requirement 3: Best Matching Paper
**Status**: ✅ **IMPLEMENTED**

- **Location**: Lines 920-925, Function `find_best_matching_paper()` (Lines 404-450)
- **Logic**: Find paper that matches query most using similarity scoring
- **Scoring Algorithm**:
  - Title similarity: 50% weight
  - Keyword overlap: 30% weight
  - Text similarity: 20% weight
  - Academic domain bonus: 1.2x multiplier (arxiv, openreview, edu, acm, ieee)
- **Implementation**:
  - Uses `SequenceMatcher` for text similarity
  - Calculates weighted scores for all results
  - Returns paper with highest score
  - Added to LLM context as special system message

### Requirement 4: Document Links Attachment
**Status**: ✅ **IMPLEMENTED**

- **Location**: Lines 1041-1095 in `main.py`
- **Logic**: Attach document links if OpenReview API or Google PSE is applied
- **OpenReview Links** (Lines 1044-1052):
  - PDF URL: `https://openreview.net/pdf?id={paper_id}`
  - Review URL: `https://openreview.net/forum?id={forum_id}`
  - Source: "openreview"
- **Google PSE Links** (Lines 1054-1077):
  - Best matching paper (marked with `is_best_match: true`)
  - Top 5 results
  - Includes title, URL, snippet
  - Source: "google_pse"
- **Response Format**:
  ```json
  {
    "document_links": [
      {
        "title": "...",
        "url": "...",
        "source": "openreview" | "google_pse",
        "is_best_match": true/false,
        "review_url": "...",  // OpenReview only
        "snippet": "..."      // Google PSE only
      }
    ]
  }
  ```

## Flow Verification

### Scenario 1: OpenReview Enabled, Papers Found
```
Input: use_openreview=True, query="paper about transformers"
Flow:
  1. Search OpenReview API → Found 2 papers
  2. Request user selection
  3. User selects paper A
  4. Skip Google PSE (openreview_has_results=True)
  5. Use OpenReview paper in context
  6. Attach OpenReview document links
✅ PASS
```

### Scenario 2: OpenReview Enabled, No Papers Found
```
Input: use_openreview=True, query="obscure topic xyz"
Flow:
  1. Search OpenReview API → No papers found
  2. openreview_has_results=False
  3. should_use_google_pse=True
  4. Search Google PSE → Found 10 results
  5. Find best matching paper
  6. Add best match to context
  7. Attach Google PSE document links
✅ PASS
```

### Scenario 3: OpenReview Enabled, User Selects "None"
```
Input: use_openreview=True, selected_paper_id="none"
Flow:
  1. Search OpenReview API → Found 3 papers
  2. Request user selection
  3. User selects "none"
  4. user_selected_none=True
  5. should_use_google_pse=True
  6. Search Google PSE → Found 10 results
  7. Find best matching paper
  8. Add best match to context
  9. Attach Google PSE document links
✅ PASS
```

### Scenario 4: OpenReview Disabled
```
Input: use_openreview=False
Flow:
  1. Skip OpenReview search
  2. should_use_google_pse=True (not request.use_openreview)
  3. Search Google PSE → Found 10 results
  4. Find best matching paper
  5. Add best match to context
  6. Attach Google PSE document links
✅ PASS
```

## Code Quality

### ✅ Error Handling
- Try-except blocks around Google PSE search (Lines 918-930)
- Graceful fallback if search fails
- Logging for debugging

### ✅ Code Organization
- Clear separation of concerns
- Well-documented logic
- Helper function for best match calculation

### ✅ Response Format
- Backward compatible (`pdf_links` still included)
- New `document_links` array with source attribution
- `search_results` metadata for Google PSE

## Summary

All requirements have been **successfully implemented**:

1. ✅ OpenReview search runs first when enabled
2. ✅ Google PSE search runs as fallback when:
   - OpenReview is off, OR
   - OpenReview has no results, OR
   - User selects "none"
3. ✅ Best matching paper is automatically found and used
4. ✅ Document links are always attached when search sources are used

The implementation follows the specified design and handles all edge cases properly.
