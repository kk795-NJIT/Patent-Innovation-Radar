#!/bin/bash
# Sprint 1: Start Docker services and verify health

set -e

YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}=== STARTING DOCKER SERVICES ===${NC}\n"

# Start all services
echo -e "${YELLOW}[1/3] Starting Docker Compose services...${NC}"
docker compose up -d

echo -e "${YELLOW}[2/3] Waiting for services to become healthy...${NC}"
sleep 5

# Check health
echo -e "${YELLOW}[3/3] Checking service health...${NC}\n"

services=(
    "postgres:5432"
    "redis:6379"
    "minio:9000"
    "qdrant:6333"
)

for service in "${services[@]}"; do
    IFS=':' read -r name port <<< "$service"
    if docker compose ps | grep -q "$name"; then
        echo -e "${GREEN}✅ $name${NC}"
    else
        echo -e "${RED}❌ $name${NC}"
    fi
done

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ DOCKER SERVICES STARTED!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

echo "Service endpoints:"
echo "  PostgreSQL: localhost:5432"
echo "  Redis: localhost:6379"
echo "  MinIO API: localhost:9000"
echo "  MinIO Console: localhost:9001 (minioadmin/minioadmin)"
echo "  Qdrant: localhost:6333"
echo "  Neo4j Bolt: localhost:7687"
echo "  Prometheus: localhost:9090"
echo "  Grafana: localhost:3000 (admin/admin)"
echo ""
echo "Next: Run ./scripts/init_database.sh to initialize the database"
echo ""
