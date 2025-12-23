#!/bin/bash
# Patent + Innovation Radar: Local Development Environment Setup

set -e

YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "$0")" && cd .. && pwd)"
VENV_PATH="$PROJECT_ROOT/venv"

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║    Patent + Innovation Radar: LOCAL DEVELOPMENT SETUP          ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if venv exists
if [ ! -d "$VENV_PATH" ]; then
    echo -e "${RED}❌ Virtual environment not found!${NC}"
    echo "Run: python3 -m venv venv"
    exit 1
fi

# Activate venv
echo -e "${YELLOW}[1/5] Activating Python virtual environment...${NC}"
source "$VENV_PATH/bin/activate"
echo -e "${GREEN}✅ Venv activated${NC}\n"

# Check Docker
echo -e "${YELLOW}[2/5] Checking Docker services...${NC}"
cd "$PROJECT_ROOT"
if docker compose ps 2>/dev/null | grep -q "postgres"; then
    echo -e "${GREEN}✅ Docker services running${NC}\n"
else
    echo -e "${YELLOW}⚠️  Docker services not running. Starting...${NC}"
    docker compose up -d
    sleep 5
    echo -e "${GREEN}✅ Docker services started${NC}\n"
fi

# Start API server in background
echo -e "${YELLOW}[3/5] Starting FastAPI server...${NC}"
cd "$PROJECT_ROOT"
python -m uvicorn services.api.main:app --host 0.0.0.0 --port 8000 --reload > /tmp/api.log 2>&1 &
API_PID=$!
echo $API_PID > /tmp/api.pid
sleep 3

if kill -0 $API_PID 2>/dev/null; then
    echo -e "${GREEN}✅ FastAPI server started (PID: $API_PID)${NC}\n"
else
    echo -e "${RED}❌ Failed to start FastAPI server${NC}"
    cat /tmp/api.log
    exit 1
fi

# Start Streamlit in a new tab (optional - macOS)
echo -e "${YELLOW}[4/5] UI options...${NC}"
echo "To start Streamlit UI, run in a new terminal:"
echo -e "${BLUE}  cd $PROJECT_ROOT && source venv/bin/activate && streamlit run services/ui/app.py${NC}\n"

# Test endpoints
echo -e "${YELLOW}[5/5] Testing API endpoints...${NC}"
health_status=$(curl -s http://localhost:8000/health | grep -o '"status":"ok"' || true)
if [ -n "$health_status" ]; then
    echo -e "${GREEN}✅ API health check passed${NC}"
else
    echo -e "${YELLOW}⚠️  API still initializing...${NC}"
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ LOCAL ENVIRONMENT READY!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo "Service endpoints:"
echo -e "  ${BLUE}FastAPI Docs:${NC}      http://localhost:8000/docs"
echo -e "  ${BLUE}FastAPI Redoc:${NC}     http://localhost:8000/redoc"
echo -e "  ${BLUE}API Health:${NC}        http://localhost:8000/health"
echo -e "  ${BLUE}PostgreSQL:${NC}        localhost:5432 (postgres/postgres)"
echo -e "  ${BLUE}Redis:${NC}             localhost:6379"
echo -e "  ${BLUE}Qdrant:${NC}            http://localhost:6333/dashboard"
echo -e "  ${BLUE}Prometheus:${NC}        http://localhost:9090"
echo -e "  ${BLUE}Grafana:${NC}           http://localhost:3000 (admin/admin)"
echo ""

echo "Quick commands:"
echo "  View API logs:         tail -f /tmp/api.log"
echo "  Stop API server:       kill $(cat /tmp/api.pid)"
echo "  Stop Docker services:  docker compose down"
echo "  Run tests:             pytest tests/ -v"
echo ""

echo "Next steps:"
echo "  1. Open http://localhost:8000/docs to test APIs"
echo "  2. Run seeds/sample data script (coming soon)"
echo "  3. Create watchlists via /watchlists endpoint"
echo "  4. Test ingestion: python services/api/ingest.py --since-days 7"
echo ""
