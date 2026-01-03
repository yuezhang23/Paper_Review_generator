# Google PSE Real-Time Search Integration

## Quick Start

This integration enables **real-time web search using Google Programmable Search Engine (PSE)** for all models except `supermind-agent-v1`.

### Files Created

1. **`backend/google_pse_service.py`** - Main service module for Google PSE search
2. **`backend/test_google_pse.py`** - Standalone test script
3. **`GOOGLE_PSE_SETUP.md`** - Detailed setup instructions

### Quick Setup

1. **Get Google API credentials:**
   - API Key: https://console.cloud.google.com/apis/credentials
   - CSE ID: https://programmablesearchengine.google.com/

2. **Add to `.env` file:**
   ```bash
   GOOGLE_API_KEY=your_api_key
   GOOGLE_CSE_ID=your_cse_id
   ```

3. **Test the setup:**
   ```bash
   cd paper_chat_app/backend
   python test_google_pse.py
   ```

### Features

- ✅ Automatic search detection based on query content
- ✅ Academic paper-focused search optimization
- ✅ Multiple query variations for better results
- ✅ Seamless integration with chat endpoint
- ✅ Works for all models except `supermind-agent-v1`

### How It Works

1. User sends a message to any model (except supermind-agent-v1)
2. System analyzes query to determine if search is needed
3. If needed, Google PSE search is performed
4. Results are formatted and added to LLM context
5. Model generates response with real-time information

### API Usage

The search is automatically enabled by default. You can control it via the `use_google_pse` parameter:

```python
# Enable (default)
{
    "model": "grok-4-fast",
    "use_google_pse": True
}

# Disable
{
    "model": "grok-4-fast",
    "use_google_pse": False
}
```

### Models Supported

| Model | Google PSE Search |
|-------|------------------|
| grok-4-fast | ✅ Yes |
| gpt-5 | ✅ Yes |
| gemini-2.5-pro | ✅ Yes |
| gemini-3-flash-preview | ✅ Yes |
| deepseek | ✅ Yes |
| supermind-agent-v1 | ❌ No (uses built-in Tavily) |

### Example Queries That Trigger Search

- "Find recent papers on transformer architectures"
- "What are the latest developments in AI in 2024?"
- "Search for papers about neural networks"
- "What papers discuss attention mechanisms?"

### Response Format

When search is used, the API response includes:

```json
{
    "message": "...",
    "search_results": {
        "source": "google_pse",
        "count": 10,
        "results": [...]
    }
}
```

### Documentation

For detailed setup instructions, see: **`GOOGLE_PSE_SETUP.md`**
