# Paper Analysis Chat Application

A ChatGPT-like GUI application for analyzing academic ML papers with a beautiful 2-column interface. The application integrates with the AI Builder API (Grok) and OpenReview API to provide comprehensive paper analysis.

## Features

- **2-Column Interface**: 
  - Left: Conversation history and paper selection
  - Right: Chat interface with paper analysis

- **Paper Search & Retrieval**:
  - Search papers from OpenReview API
  - Fallback to web search if paper not found
  - Load full paper context including metadata and reviews

- **AI-Powered Analysis**:
  - Uses Grok-4-fast model via AI Builder API
  - Detailed paper summaries
  - Context-aware responses using paper metadata and reviews
  - Visual hints and query suggestions

- **Academic Theme**:
  - Beautiful academic-themed UI
  - Paper-related query suggestions
  - Visual indicators for paper context

## Architecture

- **Backend**: FastAPI (Python)
- **Frontend**: Next.js 14 with TypeScript
- **AI Model**: Grok-4-fast via AI Builder API
- **Paper Data**: OpenReview API + Web Search fallback

## Setup

### Backend Setup

1. Navigate to backend directory:
```bash
cd backend
```

2. Create virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create `.env` file:
```bash
# AI Builder API Token (required)
AI_BUILDER_TOKEN=your_ai_builder_token_here

# OpenReview API Credentials (optional, for paper metadata and reviews)
OPENREVIEW_USERNAME=your_openreview_username
OPENREVIEW_PASSWORD=your_openreview_password
OPENREVIEW_BASEURL=https://api2.openreview.net
```

5. Run the backend:
```bash
python main.py
# Or with uvicorn directly:
uvicorn main:app --reload --port 8000
```

The backend will run on `http://localhost:8000`

### Frontend Setup

1. Navigate to frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
# or
yarn install
```

3. Create `.env.local` file (optional, defaults to localhost:8000):
```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

4. Run the frontend:
```bash
npm run dev
# or
yarn dev
```

The frontend will run on `http://localhost:3000`

## Usage

1. **Search for Papers**: Use the search bar at the top to find papers by title, keywords, or authors
2. **Load Paper Context**: Click on a search result to load the full paper context (metadata, reviews)
3. **Ask Questions**: Use the chat interface to ask questions about the paper
4. **View Suggestions**: Click on suggested queries to get started quickly
5. **Manage Conversations**: Use the left sidebar to switch between conversations

## API Endpoints

### Backend Endpoints

- `GET /` - Health check
- `GET /health` - Health status
- `GET /suggestions` - Get paper-related query suggestions
- `POST /api/search-paper` - Search for papers
- `POST /api/get-paper-context` - Get full paper context including reviews
- `POST /api/chat` - Chat with paper context
- `POST /api/chat/stream` - Streaming chat endpoint

## Project Structure

```
paper_chat_app/
├── backend/
│   ├── main.py              # FastAPI backend
│   ├── requirements.txt     # Python dependencies
│   └── .env                 # Environment variables (create this)
├── frontend/
│   ├── app/
│   │   ├── page.tsx         # Main chat interface
│   │   ├── layout.tsx       # Root layout
│   │   └── globals.css      # Global styles
│   ├── package.json         # Node dependencies
│   └── next.config.js       # Next.js config
└── README.md                # This file
```

## Features in Detail

### Paper Search
- Searches OpenReview API first
- Falls back to web search if paper not found
- Returns paper metadata, authors, abstract, venue

### Paper Context
- Retrieves full paper information
- Includes official reviews from OpenReview
- Provides metadata for enhanced analysis

### Chat Interface
- Context-aware responses using paper information
- Streaming support for real-time responses
- Conversation history management
- Visual hints and suggestions

## Technologies Used

- **Backend**: FastAPI, OpenAI SDK, OpenReview SDK, httpx
- **Frontend**: Next.js 14, React, TypeScript, Tailwind CSS
- **AI**: Grok-4-fast via AI Builder API
- **APIs**: AI Builder API, OpenReview API

## License

MIT

