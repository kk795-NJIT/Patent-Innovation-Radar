#!/bin/bash
# Sprint 1: Local Environment & Infrastructure Setup - Test Script
# This script validates the entire local setup before pushing to git

set -e
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== SPRINT 1: LOCAL ENVIRONMENT SETUP VALIDATION ===${NC}"
echo ""

# Test 1: Verify Python venv
echo -e "${YELLOW}[1/10] Testing Python venv...${NC}"
if [ -d "venv" ] && [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    python_version=$(python --version 2>&1)
    echo -e "${GREEN}✅ venv created and activated: $python_version${NC}"
else
    echo -e "${RED}❌ venv not found or invalid${NC}"
    exit 1
fi

# Test 2: Verify dependencies
echo -e "${YELLOW}[2/10] Checking critical dependencies...${NC}"
for pkg in fastapi sqlalchemy torch streamlit redis qdrant_client; do
    if python -c "import $pkg" 2>/dev/null; then
        version=$(python -c "import $pkg; print(getattr($pkg, '__version__', 'unknown'))" 2>/dev/null || echo "unknown")
        echo -e "${GREEN}✅ $pkg: $version${NC}"
    else
        echo -e "${RED}❌ $pkg not found${NC}"
        exit 1
    fi
done

# Test 3: Check Docker
echo -e "${YELLOW}[3/10] Checking Docker installation...${NC}"
if docker --version > /dev/null 2>&1; then
    docker_version=$(docker --version)
    echo -e "${GREEN}✅ $docker_version${NC}"
else
    echo -e "${RED}❌ Docker not installed${NC}"
    exit 1
fi

# Test 4: Check Docker Compose
echo -e "${YELLOW}[4/10] Checking Docker Compose...${NC}"
if docker compose version > /dev/null 2>&1; then
    compose_version=$(docker compose version)
    echo -e "${GREEN}✅ $compose_version${NC}"
else
    echo -e "${RED}❌ Docker Compose not found${NC}"
    exit 1
fi

# Test 5: Validate docker-compose.yml
echo -e "${YELLOW}[5/10] Validating docker-compose.yml...${NC}"
if docker compose config > /dev/null 2>&1; then
    echo -e "${GREEN}✅ docker-compose.yml is valid${NC}"
else
    echo -e "${RED}❌ docker-compose.yml has errors${NC}"
    exit 1
fi

# Test 6: Verify all Python files compile
echo -e "${YELLOW}[6/10] Checking Python file syntax...${NC}"
python_files=(
    "services/api/main.py"
    "services/api/ingest.py"
    "ml/models/ml_services.py"
    "services/agent/report_agent.py"
    "pipelines/kubeflow/patent_pipeline.py"
)

for file in "${python_files[@]}"; do
    if python -m py_compile "$file" 2>/dev/null; then
        echo -e "${GREEN}✅ $file${NC}"
    else
        echo -e "${RED}❌ $file has syntax errors${NC}"
        exit 1
    fi
done

# Test 7: Verify database schema file
echo -e "${YELLOW}[7/10] Checking database schema...${NC}"
if [ -f "data/schemas/patent_schema.sql" ]; then
    line_count=$(wc -l < data/schemas/patent_schema.sql)
    echo -e "${GREEN}✅ patent_schema.sql ($line_count lines)${NC}"
else
    echo -e "${RED}❌ patent_schema.sql not found${NC}"
    exit 1
fi

# Test 8: Verify .env.sample
echo -e "${YELLOW}[8/10] Checking .env.sample...${NC}"
if [ -f ".env.sample" ]; then
    if [ ! -f ".env" ]; then
        echo -e "${YELLOW}Note: .env file not found. Creating from .env.sample...${NC}"
        cp .env.sample .env
        echo -e "${GREEN}✅ .env created from .env.sample${NC}"
    else
        echo -e "${GREEN}✅ .env already exists${NC}"
    fi
else
    echo -e "${RED}❌ .env.sample not found${NC}"
    exit 1
fi

# Test 9: Check directory structure
echo -e "${YELLOW}[9/10] Verifying directory structure...${NC}"
directories=(
    "services/api"
    "services/agent"
    "services/ui"
    "ml/models"
    "ml/features"
    "pipelines/kubeflow"
    "data/schemas"
    "infra/monitoring"
    "docs"
    "tests"
)

for dir in "${directories[@]}"; do
    if [ -d "$dir" ]; then
        echo -e "${GREEN}✅ $dir${NC}"
    else
        echo -e "${RED}❌ $dir missing${NC}"
        exit 1
    fi
done

# Test 10: Verify critical documentation
echo -e "${YELLOW}[10/10] Checking documentation...${NC}"
docs=(
    "README.md"
    "PRODUCT_SPEC.md"
    "ARCHITECTURE.md"
    "PROJECT_SUMMARY.md"
)

for doc in "${docs[@]}"; do
    if [ -f "$doc" ]; then
        echo -e "${GREEN}✅ $doc${NC}"
    else
        echo -e "${RED}❌ $doc missing${NC}"
        exit 1
    fi
done

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ SPRINT 1 VALIDATION COMPLETE!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Start Docker services:    docker compose up -d"
echo "2. Initialize database:      docker compose exec postgres psql -U postgres -d patent_radar -f /docker-entrypoint-initdb.d/patent_schema.sql"
echo "3. Test API:                 curl http://localhost:8000/health"
echo "4. View UI:                  open http://localhost:8501"
echo ""
