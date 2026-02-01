#!/bin/bash

# Start script for Paper Chat Application

echo "🚀 Starting Paper Chat Application..."
echo ""

# Load backend .env if present (for USE_GATEWAY_ORCHESTRATOR, AI_BUILDER_TOKEN, etc.)
if [ -f "backend/.env" ]; then
    set -a
    source backend/.env
    set +a
fi

# Check if .env exists in backend
if [ ! -f "backend/.env" ]; then
    echo "⚠️  Warning: backend/.env file not found"
    echo "   Please create it with AI_BUILDER_TOKEN and optional OpenReview credentials"
    echo ""
fi

# Parse flags
for arg in "$@"; do
    case "$arg" in
        --with-gateway|-gw) export USE_GATEWAY_ORCHESTRATOR=true ;;
    esac
done

# Check if GROBID should be started
if [ "$1" == "--with-grobid" ] || [ "$1" == "-g" ]; then
    echo "📄 Starting GROBID service..."
    if command -v docker-compose &> /dev/null || command -v docker &> /dev/null; then
        # Use docker-compose if available, otherwise docker compose
        if command -v docker-compose &> /dev/null; then
            docker-compose -f docker-compose.grobid.yml up -d
        else
            docker compose -f docker-compose.grobid.yml up -d
        fi
        echo "   GROBID started at http://localhost:8070"
        echo "   Waiting for GROBID to be ready..."
        sleep 10
    else
        echo "⚠️  Docker not found. Please install Docker to run GROBID."
        echo "   You can also run GROBID manually or set GROBID_URL in backend/.env"
    fi
    echo ""
fi

# Start backend
echo "📦 Starting FastAPI backend (port 8000, non-LLM)..."
cd backend
python3 -m venv venv 2>/dev/null || true
source venv/bin/activate
pip install -r requirements.txt --quiet

# Architecture: main (8000) = non-LLM; gateway (8010) = all LLM
[ "$USE_GATEWAY_ORCHESTRATOR" = "true" ] || [ "$USE_GATEWAY_ORCHESTRATOR" = "1" ] && export USE_GATEWAY_ORCHESTRATOR=true

python main.py &
BACKEND_PID=$!

# When gateway enabled, also start gateway (8010) for LLM endpoints
GATEWAY_PID=""
if [ "$USE_GATEWAY_ORCHESTRATOR" = "true" ] || [ "$USE_GATEWAY_ORCHESTRATOR" = "1" ]; then
    echo "📦 Starting Gateway (port 8010, LLM)..."
    export MAIN_BACKEND_URL="${MAIN_BACKEND_URL:-http://localhost:8000}"
    python -m orchestrator_backup.main &
    GATEWAY_PID=$!
fi
cd ..

# Wait for backend(s) to start
sleep 3

# Start frontend
echo "🎨 Starting Next.js frontend..."
cd frontend
if [ ! -d "node_modules" ]; then
    echo "   Installing dependencies..."
    npm install
fi
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "✅ Application started!"
echo "   Main backend (non-LLM): http://localhost:8000"
if [ "$USE_GATEWAY_ORCHESTRATOR" = "true" ] || [ "$USE_GATEWAY_ORCHESTRATOR" = "1" ]; then
    echo "   Gateway (LLM): http://localhost:8010"
    echo "   Tip: set NEXT_PUBLIC_USE_GATEWAY=true in frontend/.env.local"
fi
echo "   Frontend: http://localhost:3000"
if [ "$1" == "--with-grobid" ] || [ "$1" == "-g" ]; then
    echo "   GROBID: http://localhost:8070"
fi
echo ""
echo "Press Ctrl+C to stop all servers"

# Wait for user interrupt
cleanup() {
    kill $BACKEND_PID $GATEWAY_PID $FRONTEND_PID 2>/dev/null || true
    exit
}
trap cleanup INT TERM
wait

