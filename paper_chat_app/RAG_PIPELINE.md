# RAG Pipeline Implementation

## Overview

The application now implements a **Retrieval-Augmented Generation (RAG)** pipeline that uses OpenReview API as the retrieval source. When a chat query triggers a paper search, the system retrieves relevant papers from OpenReview first, then combines them with the model response.

## RAG Pipeline Architecture

The RAG pipeline consists of 4 main stages:

### 1. Query Intent Extraction
**Function**: `extract_query_intent(messages)`

- Analyzes the user's message to determine if paper retrieval is needed
- Detects paper-related keywords (e.g., "paper", "find", "search", "arxiv", "ICLR", etc.)
- Returns the query string if paper retrieval should be triggered

### 2. Retrieval
**Function**: `rag_retrieve(query, limit=5)`

- Queries OpenReview API to retrieve relevant papers
- Searches based on the extracted query intent
- Returns a list of retrieved papers with:
  - Title
  - Authors
  - Abstract (full text for better context)
  - Venue
  - PDF URL
  - Forum URL

### 3. Augmentation
**Function**: `rag_augment(retrieved_papers)`

- Formats retrieved papers into structured context
- Creates a comprehensive context string with:
  - Clear section markers ("=== RETRIEVED PAPERS FROM OPENREVIEW ===")
  - Full paper information (title, authors, abstract, links)
  - Instructions for the model on how to use the retrieved information
- Returns formatted context string for LLM

### 4. Generation
**Function**: `chat()` endpoint

- Combines augmented context with user query
- Sends to AI model (any model: Grok, GPT-5, Gemini, DeepSeek, etc.)
- Model generates response grounded in retrieved papers
- Returns response with PDF links attached

## Implementation Details

### Main RAG Function
```python
async def build_messages_with_rag(request: ChatRequest) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    RAG Pipeline - Build messages with Retrieval-Augmented Generation
    Returns: (messages, retrieved_papers)
    """
```

This function:
1. Extracts query intent from user messages
2. Retrieves papers from OpenReview if needed
3. Augments context with retrieved papers
4. Builds complete message list for LLM

### Key Features

1. **Automatic Triggering**: RAG is automatically triggered when:
   - User query contains paper-related keywords
   - No explicit paper context is already provided

2. **Full Abstract Context**: Unlike simple search, RAG includes full abstracts for better understanding

3. **Structured Formatting**: Retrieved papers are formatted with clear markers so the model knows they're from RAG

4. **PDF Link Extraction**: Retrieved papers automatically include PDF links for frontend display

5. **Works with All Models**: RAG pipeline works with any AI model, not just Supermind Agent

## RAG vs Simple Search

### Before (Simple Search)
- Papers added to context as simple list
- Limited information (title, authors, truncated abstract)
- Model may not understand these are retrieved results

### After (RAG Pipeline)
- Papers clearly marked as "RETRIEVED PAPERS FROM OPENREVIEW"
- Full abstracts included for better context
- Explicit instructions to model to use retrieved papers
- Better grounding in actual research

## Example Flow

1. **User Query**: "Find papers about transformer architectures"

2. **Query Intent Extraction**: 
   - Detects "papers" and "transformer" keywords
   - Extracts query: "Find papers about transformer architectures"

3. **Retrieval**:
   - Searches OpenReview for "transformer architectures"
   - Retrieves top 5 relevant papers

4. **Augmentation**:
   - Formats papers with full information
   - Creates context: "=== RETRIEVED PAPERS FROM OPENREVIEW === ..."

5. **Generation**:
   - Model receives: System prompt + Retrieved papers + User query
   - Model generates response grounded in retrieved papers
   - Response includes references to specific papers with PDF links

## Benefits

1. **Accuracy**: Responses are grounded in actual retrieved papers, not general knowledge
2. **Relevance**: Only relevant papers are retrieved based on query
3. **Transparency**: Retrieved papers are clearly marked in context
4. **Completeness**: Full abstracts provide better context than summaries
5. **Universal**: Works with all AI models, not just search-capable ones

## Technical Notes

- RAG is only triggered when no explicit `paper_context` is provided
- If user has already selected a specific paper, that context takes precedence
- Retrieved papers are limited to 5 for performance and token efficiency
- PDF links are automatically extracted and returned to frontend
- The `rag_retrieved_count` field in response indicates RAG was used

