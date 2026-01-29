# AI Paper Reviewer

An intelligent paper review system that integrates with OpenReview through a Model Context Protocol (MCP) server. This project provides tools to search, retrieve, and analyze academic papers from OpenReview, with a focus on ICLR and other major conferences.

## Features

- **OpenReview MCP Server**: A Model Context Protocol server that wraps the OpenReview Python SDK
- **Paper Search**: Search for papers by title, content, or venue (e.g., ICLR 2025)
- **Profile Lookup**: Retrieve OpenReview user profiles
- **Review Access**: Get reviews and meta-reviews for submissions
- **Group Information**: Access conference and venue group details

## Installation

1. Clone this repository:
```bash
git clone https://github.com/YOUR_USERNAME/AI_Paper_Reviewer.git
cd AI_Paper_Reviewer
```

2. Install dependencies:
```bash
pip install -r openreview_mcp/requirements_openreview.txt
```

3. Set up environment variables:
Create a `.env` file in the root directory with your OpenReview credentials:
```bash
OPENREVIEW_USERNAME=your_username
OPENREVIEW_PASSWORD=your_password
OPENREVIEW_BASEURL=https://api2.openreview.net
```

## Usage

### Testing the OpenReview Connection

Run the test script to search for papers:
```bash
python openreview_mcp/test_openreview_search.py
```

This will:
- Authenticate with OpenReview
- Search for papers from ICLR 2025 with "generative" in the title
- Display results and randomly select one

### Using the MCP Server

The MCP server provides the following tools:

1. **get_profile(email)**: Retrieve OpenReview profile information
2. **search_notes(title, content, venue, limit)**: Search for papers/submissions
3. **get_note(note_id)**: Get a specific note by ID
4. **get_reviews(note_id)**: Get all reviews for a note
5. **get_group(group_id)**: Get group information
6. **get_invitations(group_id, invitation_id, limit)**: Get invitation information

### Setting up MCP in Cursor

1. Locate Cursor's MCP configuration file:
   - macOS: `~/Library/Application Support/Cursor/User/globalStorage/mcp.json`
   - Linux: `~/.config/Cursor/User/globalStorage/mcp.json`
   - Windows: `%APPDATA%\Cursor\User\globalStorage\mcp.json`

2. Add the server configuration:
```json
{
  "mcpServers": {
    "openreview": {
      "command": "python",
      "args": [
        "/absolute/path/to/superlinear_ws/openreview_mcp/openreview_mcp.py"
      ],
      "description": "OpenReview MCP Server - Wraps the OpenReview Python SDK"
    }
  }
}
```

3. Restart Cursor for changes to take effect.

## Project Structure

```
superlinear_ws/
├── openreview_mcp/
│   ├── openreview_mcp.py          # Main MCP server implementation
│   ├── test_openreview_search.py  # Test script for OpenReview API
│   ├── requirements_openreview.txt # Python dependencies
│   └── OPENREVIEW_MCP_README.md   # Detailed MCP setup instructions
├── paper_chat_app/
│   └── backend/
│       └── orchestrator_backup/   # Backup MCP orchestrator gateway (FastAPI + LangGraph)
├── docs/
│   └── README.md                  # This file
└── .gitignore                     # Git ignore rules
```

## Backup MCP Orchestrator Gateway (`orchestrator_backup`)

The `paper_chat_app/backend/orchestrator_backup` module implements a **backup AI orchestrator** that can replace the original MCP/AI Builder gateway when it is unavailable.

### What the backup orchestrator provides

1. **FastAPI app + CORS**
   - App entrypoint: `paper_chat_app/backend/orchestrator_backup/main.py`
   - Runs as a standalone service (e.g. on port `8010`).

2. **Gateway auth (shared token)**
   - All orchestrator routes require:
     - `Authorization: Bearer <token>`
   - Token is read from an environment variable:
     - `MCP_GATEWAY_TOKEN` (configurable via `mcp_gateway_config.yaml`).

3. **MCP-style provider config**
   - Config file: `paper_chat_app/backend/orchestrator_backup/mcp_gateway_config.yaml`
   - Loaded via:
     - `MCP_GATEWAY_CONFIG_PATH` (optional, overrides default path).
   - Each provider entry defines:
     - `name`: logical provider name (e.g. `ai_builders`, `openai`)
     - `type`: currently `openai_compatible`
     - `base_url`: upstream OpenAI-compatible URL
     - `api_key_env`: env var with the upstream API key
     - `models`: list of model IDs routed to this provider

4. **Chat orchestration (LangGraph)**
   - Graph defined in: `orchestrator_backup/graph.py`
   - Steps:
     1. **Route node** selects provider based on `model` and config.
     2. **Call-provider node**:
        - Builds a `ChatOpenAI` client (from `langchain-openai`) pointing at the provider’s `base_url`.
        - Invokes the model with the OpenAI chat messages from the request.
        - Returns an OpenAI-compatible `chat.completion` JSON.
   - Exposed as OpenAI-compatible endpoints:
     - `GET /backend/v1/models`
       - Returns `{"object": "list", "data": [...]}` for all configured models.
     - `POST /backend/v1/chat/completions`
       - Accepts standard chat body: `{ "model": "...", "messages": [...], ... }`
       - Returns `chat.completion` response.

5. **Agentic methodology image flow (reusing `image_methodos_generator`)**
   - A second LangGraph (`build_image_agent_graph`) orchestrates the full methodology-image pipeline:
     1. Resolve PDF + build/load RAG index (`resolve_pdf_and_index`).
     2. Retrieve methodology chunks (`retrieve_methodology_chunks`).
     3. Combine & validate chunks (`combine_and_validate_chunks`).
     4. Generate step-by-step interpretation with an LLM (`generate_interpretation`).
     5. Save interpretation and create a request directory (`save_interpretation_and_create_request_dir`).
     6. Generate a whiteboard/render prompt via the three-layer generator (`generate_whiteboard_prompt`).
     7. Generate and rank images (`generate_image`), returning the best one.
   - This agentic flow is exposed via:
     - `POST /backend/v1/agents/methodology/summary-image`
     - Request body: `ImageGenerationRequest` (same fields as `/api/generate-summary-image` in the main backend).
     - Response includes:
       - `image_url`: path/URL of the chosen image
       - `image_bytes_b64`: base64-encoded image bytes
       - `revised_prompt`: final whiteboard/render prompt
       - `methodology_steps`: interpreted step-by-step methodology text

### Step-by-step: running the backup orchestrator

1. **Install backend dependencies** (from repo root):
   ```bash
   cd paper_chat_app/backend
   pip install -r requirements.txt
   ```
2. **Set required environment variables**:
   ```bash
   export MCP_GATEWAY_TOKEN="your-shared-token"
   export AI_BUILDER_TOKEN="your-ai-builder-or-backend-key"   # if using ai_builders provider
   # Optional: additional providers (e.g. OpenAI)
   # export OPENAI_API_KEY="sk-..."
   # Optional: custom config path
   # export MCP_GATEWAY_CONFIG_PATH="/abs/path/to/mcp_gateway_config.yaml"
   ```
3. **Start the backup orchestrator**:
   ```bash
   uvicorn orchestrator_backup.main:app --host 0.0.0.0 --port 8010
   ```
4. **List available models**:
   ```bash
   curl -sS http://localhost:8010/backend/v1/models \
     -H "Authorization: Bearer $MCP_GATEWAY_TOKEN"
   ```
5. **Call chat completions through the backup gateway**:
   ```bash
   curl -sS http://localhost:8010/backend/v1/chat/completions \
     -H "Authorization: Bearer $MCP_GATEWAY_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "model": "grok-4-fast",
       "messages": [{"role": "user", "content": "Say hello in one sentence."}],
       "temperature": 0.2
     }'
   ```
6. **Run the methodology image agent**:
   ```bash
   curl -sS http://localhost:8010/backend/v1/agents/methodology/summary-image \
     -H "Authorization: Bearer $MCP_GATEWAY_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "file_ids": ["<uploaded-file-id>"],
       "figure_extraction_method": "none",
       "table_extraction_method": "none"
     }'
   ```

### Step-by-step: switching the main backend to use the backup

The existing `paper_chat_app/backend` code uses an OpenAI-compatible client for the AI Builder gateway. You can redirect it to the backup orchestrator without code changes:

1. **Point the base URL to the backup**:
   ```bash
   export AI_BUILDER_BASE_URL="http://localhost:8010/backend/v1"
   ```
2. **Use the gateway token as the AI key**:
   ```bash
   export AI_BUILDER_TOKEN="$MCP_GATEWAY_TOKEN"
   ```
3. **Restart the main backend**:
   - All calls that previously went to the hosted AI Builder endpoint will now route through the local backup orchestrator, including:
     - `/api/chat`, `/api/get-paper-reviews`, etc.
     - The multi-agent `supermind-agent-v1` flows.

## Example: Searching for Papers

```python
import sys
sys.path.append('openreview_mcp')
from openreview_mcp import get_client
import openreview

client = get_client()

# Search for papers from ICLR 2025 with "generative" in title
venue_id = "ICLR.cc/2025/Conference"
venue_group = client.get_group(venue_id)
submission_name = venue_group.content['submission_name']['value']
invitation = f'{venue_id}/-/{submission_name}'

notes = client.get_all_notes(invitation=invitation)

# Filter for papers with "generative" in title
generative_papers = [
    note for note in notes 
    if 'generative' in note.content['title']['value'].lower()
]
```

## Requirements

- Python 3.9+
- fastmcp >= 0.9.0
- openreview-py >= 1.0.0
- python-dotenv >= 1.0.0

## Security Note

⚠️ **Important**: Never commit your `.env` file or expose your OpenReview credentials. The `.gitignore` file is configured to exclude `.env` files.

## License

This project is open source and available under the MIT License.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## References

- [OpenReview API Documentation](https://docs.openreview.net/getting-started/using-the-api)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [OpenReview Python SDK](https://github.com/openreview/openreview-py)

