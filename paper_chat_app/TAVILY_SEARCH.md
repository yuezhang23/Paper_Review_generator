# Real-Time Tavily Search in Chat

## ✅ Compatibility Status

**Yes, the chat window is fully compatible with real-time Tavily search!**

## How It Works

### Automatic Search with Supermind Agent

When you select **"Supermind Agent"** (`supermind-agent-v1`) from the model dropdown, the chat automatically gains real-time Tavily search capabilities.

### How Tavily Search is Triggered

1. **Automatic Detection**: The `supermind-agent-v1` model automatically detects when web search is needed based on the user's question
2. **Real-Time Search**: When the model determines search is needed, it automatically calls the Tavily search API through the AI Builder API
3. **Seamless Integration**: Search results are automatically incorporated into the model's response
4. **No Manual Steps**: Users don't need to do anything special - just ask questions!

### Example Use Cases

The model will automatically search when you ask:
- "Find recent papers on transformer architectures"
- "What are the latest developments in reinforcement learning?"
- "Search for papers by [author name]"
- "What papers discuss [topic]?"
- Any question requiring current or external information

### Models with Search Support

- ✅ **Supermind Agent** (`supermind-agent-v1`) - **Has automatic Tavily search**
- ❌ Other models (Grok-4 Fast, GPT-5, Gemini, DeepSeek) - No built-in search

### Visual Indicator

When `supermind-agent-v1` is selected, you'll see a "🔍 Web Search Enabled" indicator in the header to remind you that search is active.

## Technical Details

### Backend Implementation

- The chat endpoint (`/api/chat`) passes the selected model to the AI Builder API
- When `supermind-agent-v1` is used, the AI Builder API orchestrator automatically:
  1. Detects when search is needed
  2. Calls Tavily search API
  3. Incorporates results into the response
  4. Returns the enhanced answer

### System Prompt Enhancement

The system prompt has been updated to encourage the model to use web search when:
- Papers are not in the current context
- Information is missing or outdated
- Users ask about recent developments
- External sources are needed

## Usage

1. **Select Supermind Agent** from the model dropdown
2. **Ask any question** - the model will automatically search if needed
3. **Get enhanced responses** with real-time information from Tavily

## Example Conversation

**User**: "Find papers about neural architecture search from 2024"

**Supermind Agent** (automatically):
1. Detects need for search
2. Searches Tavily for "neural architecture search 2024"
3. Retrieves recent papers
4. Provides answer with sources

All of this happens automatically - no manual search needed!

