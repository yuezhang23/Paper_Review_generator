#!/bin/bash

# Start script for Paper Chat Application

echo "🚀 Starting Paper Chat Application..."
echo ""

# Check if .env exists in backend
if [ ! -f "backend/.env" ]; then
    echo "⚠️  Warning: backend/.env file not found"
    echo "   Please create it with AI_BUILDER_TOKEN and optional OpenReview credentials"
    echo ""
fi

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
echo "📦 Starting FastAPI backend..."
cd backend
python3 -m venv venv 2>/dev/null || true
source venv/bin/activate
pip install -r requirements.txt --quiet
python main.py &
BACKEND_PID=$!
cd ..

# Wait for backend to start
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
echo "   Backend: http://localhost:8000"
echo "   Frontend: http://localhost:3000"
if [ "$1" == "--with-grobid" ] || [ "$1" == "-g" ]; then
    echo "   GROBID: http://localhost:8070"
fi
echo ""
echo "Press Ctrl+C to stop all servers"

# Wait for user interrupt
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait

