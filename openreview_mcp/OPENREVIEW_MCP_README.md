# OpenReview MCP Server

This is a Model Context Protocol (MCP) server that wraps the OpenReview Python SDK, providing easy access to OpenReview API functionality through MCP tools.

## Installation

1. Install the required dependencies:
```bash
pip install -r requirements_openreview.txt
```

Or install directly:
```bash
pip install fastmcp openreview-py
```

## Configuration

Set the following environment variables for OpenReview authentication:

```bash
export OPENREVIEW_USERNAME="your_username"
export OPENREVIEW_PASSWORD="your_password"
export OPENREVIEW_BASEURL="https://api2.openreview.net"  # Optional, defaults to this
```

## Available Tools

The MCP server provides the following tools:

1. **get_profile(email: str)** - Retrieve OpenReview profile information for a given email address
2. **search_notes(content, title, venue, limit)** - Search for notes (papers/submissions) in OpenReview
3. **get_note(note_id: str)** - Retrieve a specific note (paper/submission) by its ID
4. **get_reviews(note_id: str)** - Retrieve all reviews for a specific note
5. **get_group(group_id: str)** - Retrieve information about an OpenReview group
6. **get_invitations(group_id, invitation_id, limit)** - Retrieve invitations from OpenReview

## Setting up in Cursor

To add this MCP server to Cursor:

1. **Locate Cursor's MCP configuration file**: The `mcp.json` file is typically located in:
   - macOS: `~/Library/Application Support/Cursor/User/globalStorage/mcp.json`
   - Linux: `~/.config/Cursor/User/globalStorage/mcp.json`
   - Windows: `%APPDATA%\Cursor\User\globalStorage\mcp.json`

2. **Add the server configuration**: Open the `mcp.json` file and add the following entry (or merge with existing `mcpServers`):

```json
{
  "mcpServers": {
    "openreview": {
      "command": "python",
      "args": [
        "/Users/zhangyue/Documents/superlinear_ws/openreview_mcp.py"
      ],
      "description": "OpenReview MCP Server - Wraps the OpenReview Python SDK to provide access to OpenReview API functionality"
    }
  }
}
```

**Note**: Update the path in the `args` array to match your actual file location.

3. **Restart Cursor** for the changes to take effect.

## Testing

You can test the MCP server directly by running:

```bash
python openreview_mcp.py
```

This will start the MCP server in stdio mode, which is how Cursor will interact with it.

## References

- [OpenReview API Documentation](https://docs.openreview.net/getting-started/using-the-api)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [OpenReview Python SDK](https://github.com/openreview/openreview-py)

