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
├── docs/
│   └── README.md                  # This file
└── .gitignore                     # Git ignore rules
```

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

