# Google PSE (Programmable Search Engine) Setup Guide

## Overview

This guide explains how to set up and use Google Programmable Search Engine (PSE) for real-time search functionality in the Paper Chat Application. Google PSE enables all models (except supermind-agent-v1) to perform real-time web searches.

## Features

- ✅ **Real-time web search** for all models except `supermind-agent-v1`
- ✅ **Automatic search detection** - determines when search is needed
- ✅ **Academic paper focus** - optimized queries for research papers
- ✅ **Multiple query variations** - enhanced search with query expansion
- ✅ **Seamless integration** - search results automatically included in chat context

## Setup Instructions

### Step 1: Get Google API Key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the **Custom Search API**:
   - Navigate to "APIs & Services" > "Library"
   - Search for "Custom Search API"
   - Click "Enable"

4. Create API credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "API Key"
   - Copy your API key
   - (Optional) Restrict the API key to "Custom Search API" for security

### Step 2: Create Custom Search Engine

1. Go to [Google Programmable Search Engine](https://programmablesearchengine.google.com/)
2. Click "Add" to create a new search engine
3. Configure your search engine:
   - **Sites to search**: 
     - For academic papers: `*.edu`, `*.org`, `arxiv.org`, `openreview.net`
     - For general web: Leave empty or add specific sites
   - **Name**: Give it a descriptive name (e.g., "Academic Paper Search")
4. Click "Create"
5. After creation, go to "Setup" > "Basics"
6. Copy your **Search Engine ID** (CSE ID)

### Step 3: Configure Environment Variables

Add the following to your `.env` file in the `paper_chat_app/backend/` directory:

```bash
GOOGLE_API_KEY=your_google_api_key_here
GOOGLE_CSE_ID=your_custom_search_engine_id_here
```

**Example:**
```bash
GOOGLE_API_KEY=AIzaSyBxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GOOGLE_CSE_ID=012345678901234567890:abcdefghijk
```

### Step 4: Test the Setup

Run the test script to verify your configuration:

```bash
cd paper_chat_app/backend
python test_google_pse.py
```

You should see test results confirming that:
- Configuration is correct
- Search queries work
- Results are returned properly

## Usage

### Automatic Search

Google PSE search is **automatically enabled** for all models except `supermind-agent-v1`. The system automatically detects when a query needs real-time search based on:

- Keywords like "find", "search", "latest", "recent", "current"
- Question words ("what", "who", "when", "where", "why", "how")
- Date references ("2024", "recent", "latest")
- Academic paper queries

### Manual Control

You can control Google PSE search via the API:

```python
# Enable Google PSE search (default: True)
{
    "messages": [...],
    "model": "grok-4-fast",
    "use_google_pse": True  # Enable search
}

# Disable Google PSE search
{
    "messages": [...],
    "model": "grok-4-fast",
    "use_google_pse": False  # Disable search
}
```

### Models with Google PSE

- ✅ **grok-4-fast** - Has Google PSE search
- ✅ **gpt-5** - Has Google PSE search
- ✅ **gemini-2.5-pro** - Has Google PSE search
- ✅ **gemini-3-flash-preview** - Has Google PSE search
- ✅ **deepseek** - Has Google PSE search
- ❌ **supermind-agent-v1** - Uses built-in Tavily search (no Google PSE)

## How It Works

1. **Query Analysis**: The system analyzes the user's query to determine if real-time search is needed
2. **Search Execution**: If needed, Google PSE is called with optimized academic-focused queries
3. **Result Formatting**: Search results are formatted and added to the LLM context
4. **Response Generation**: The model generates a response incorporating the search results

## API Response Format

When Google PSE search is used, the API response includes search metadata:

```json
{
    "message": "Response text...",
    "model": "grok-4-fast",
    "usage": {...},
    "search_results": {
        "source": "google_pse",
        "count": 10,
        "results": [
            {
                "title": "Paper Title",
                "url": "https://example.com/paper",
                "snippet": "Paper abstract..."
            }
        ]
    }
}
```

## Troubleshooting

### Error: "Google PSE not configured"

**Solution**: Make sure both `GOOGLE_API_KEY` and `GOOGLE_CSE_ID` are set in your `.env` file.

### Error: "Google PSE API error: 403"

**Solution**: 
- Check that the Custom Search API is enabled in Google Cloud Console
- Verify your API key is correct
- Check if API key restrictions are blocking the request

### Error: "Google PSE API error: 400"

**Solution**:
- Verify your CSE ID is correct
- Check that your Custom Search Engine is active
- Ensure the search engine is configured properly

### No Results Returned

**Solution**:
- Check your Custom Search Engine configuration
- Verify the sites you're searching are accessible
- Try a different query to test if the search engine is working

## Cost Considerations

Google Custom Search API has a free tier:
- **100 queries per day** for free
- Additional queries are charged per 1,000 queries

Monitor your usage in the [Google Cloud Console](https://console.cloud.google.com/apis/api/customsearch.googleapis.com/quotas).

## Security Best Practices

1. **Restrict API Key**: Limit your API key to only the Custom Search API
2. **Use Environment Variables**: Never commit API keys to version control
3. **Monitor Usage**: Set up billing alerts in Google Cloud Console
4. **Rotate Keys**: Regularly rotate your API keys for security

## Example Queries

Here are some example queries that will trigger Google PSE search:

- "Find recent papers on transformer architectures"
- "What are the latest developments in reinforcement learning?"
- "Search for papers about neural architecture search from 2024"
- "What papers discuss attention mechanisms?"
- "Find research on GPT-4 improvements"

## Support

For issues or questions:
1. Check the test script output: `python test_google_pse.py`
2. Review Google Cloud Console logs
3. Check the application logs for `[Google PSE]` messages
