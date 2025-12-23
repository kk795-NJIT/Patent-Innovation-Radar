#!/bin/bash
# Sprint 2: Initialize database schema and test data
# Run after docker compose up -d and all services are healthy

set -e

YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}=== INITIALIZING DATABASE ===${NC}\n"

# Wait for PostgreSQL to be ready
echo -e "${YELLOW}[1/4] Waiting for PostgreSQL to be ready...${NC}"
for i in {1..30}; do
    if docker compose exec -T postgres pg_isready -U postgres > /dev/null 2>&1; then
        echo -e "${GREEN}✅ PostgreSQL is ready${NC}\n"
        break
    fi
    echo "Attempt $i/30: Waiting for PostgreSQL..."
    sleep 2
done

# Load schema
echo -e "${YELLOW}[2/4] Loading database schema...${NC}"
if docker compose exec -T postgres psql -U postgres -d patent_radar -f /docker-entrypoint-initdb.d/patent_schema.sql > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Schema loaded successfully${NC}\n"
else
    echo -e "${RED}❌ Failed to load schema${NC}\n"
    exit 1
fi

# Verify tables
echo -e "${YELLOW}[3/4] Verifying tables...${NC}"
table_count=$(docker compose exec -T postgres psql -U postgres -d patent_radar -tc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" | tr -d ' ')
echo -e "${GREEN}✅ Found $table_count tables${NC}\n"

# Test connectivity
echo -e "${YELLOW}[4/4] Testing database connectivity...${NC}"
if docker compose exec -T postgres psql -U postgres -d patent_radar -c "SELECT version();" | grep -q "PostgreSQL"; then
    echo -e "${GREEN}✅ Database connectivity verified${NC}\n"
else
    echo -e "${RED}❌ Database connectivity test failed${NC}\n"
    exit 1
fi

echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ DATABASE INITIALIZATION COMPLETE!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

echo "Database info:"
echo "  Host: localhost"
echo "  Port: 5432"
echo "  Database: patent_radar"
echo "  User: postgres"
echo "  Password: postgres"
echo ""
echo "Connect with: psql -h localhost -U postgres -d patent_radar"
echo ""
