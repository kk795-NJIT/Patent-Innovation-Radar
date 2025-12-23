# Patent + Innovation Radar: Operational Runbooks

## Runbook: Daily Data Ingestion Failure

**Alert**: `HighIngestionLag` or `LowEmbeddingCoverage`

### Symptoms
- No new patents in database for >24 hours
- PatentsView API returning errors
- Postgres connection pool exhausted

### Diagnosis
```bash
# Check last ingestion
docker-compose exec postgres psql -U postgres -d patent_radar -c \
  "SELECT MAX(publication_date) FROM patents;"

# Check API health
curl https://api.patentsview.org/patents/query \
  -d 'q={"patent_date":{"gte":"2024-01-01"}}' | head -20

# Check Postgres connections
docker-compose exec postgres psql -U postgres -d patent_radar -c \
  "SELECT COUNT(*) FROM pg_stat_activity;"

# Check Celery worker status
docker-compose logs celery | tail -50
```

### Recovery
```bash
# Option 1: Restart Celery worker
docker-compose restart celery

# Option 2: Clear connection pool and retry
docker-compose exec postgres psql -U postgres -d patent_radar -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle';"

# Option 3: Manual ingestion
docker-compose exec api python -m services.api.ingest \
  --since-days 2 --batch-size 500

# Verify recovery
docker-compose exec postgres psql -U postgres -d patent_radar -c \
  "SELECT COUNT(*) as new_patents FROM patents \
   WHERE ingested_at > NOW() - INTERVAL '1 hour';"
```

### Prevention
- Monitor `patent_ingestion_lag_hours` daily
- Increase Postgres `max_connections` if trend shows growth
- Add retry logic to Celery tasks with exponential backoff

---

## Runbook: Embedding Service Failures

**Alert**: `LowEmbeddingCoverage` or embedding latency spike

### Symptoms
- Embeddings not computed for new patents
- Qdrant connection errors
- GPU/CPU exhaustion on embedding worker

### Diagnosis
```bash
# Check Qdrant health
curl http://localhost:6333/health

# Check vector count
curl http://localhost:6333/collections/patents | jq '.result.points_count'

# Check embedding queue
docker-compose exec api python -c \
  "from ml.models.ml_services import EmbeddingService; \
   s = EmbeddingService(); \
   print(len(s.model))"

# Monitor GPU (if available)
docker-compose exec api nvidia-smi

# Check recent errors
docker-compose logs api | grep -i "embedding" | tail -20
```

### Recovery
```bash
# Restart embedding worker
docker-compose restart api

# Force re-embed patents (CPU fallback)
docker-compose exec api python ml/models/embed_batch.py \
  --batch-size 16 --device cpu

# Rebuild Qdrant index
docker-compose exec qdrant curl -X POST http://localhost:6333/collections/patents/points/search_batch \
  -H "Content-Type: application/json" \
  -d '{"searches": [{"vector": [0] * 768, "limit": 1}]}'

# Monitor progress
watch "curl http://localhost:6333/collections/patents | jq '.result.points_count'"
```

### Prevention
- Pre-allocate GPU memory to prevent OOM crashes
- Use batching (batch_size=32 for GPU, 16 for CPU)
- Monitor embedding queue depth with metric: `embeddings_queue_depth`

---

## Runbook: Topic Model Degradation

**Alert**: `TopicModelStale` or coherence drops >10%

### Symptoms
- Topic keywords become irrelevant
- New patents assigned to wrong topics
- Topic overlap increases

### Diagnosis
```bash
# Check model age
docker-compose exec postgres psql -U postgres -d patent_radar -c \
  "SELECT model_version, coherence_score FROM topics \
   ORDER BY model_version DESC LIMIT 1;"

# Check topic quality
docker-compose exec postgres psql -U postgres -d patent_radar -c \
  "SELECT topic_id, COUNT(*) as count, coherence_score \
   FROM topics GROUP BY topic_id ORDER BY count DESC LIMIT 20;"

# Manually inspect topic keywords
docker-compose exec api python -c \
  "from ml.models.ml_services import TopicModelingService; \
   s = TopicModelingService(); \
   model = BERTopic.load('models/bertopic_v1'); \
   print(model.get_topics())"
```

### Recovery
```bash
# Retrain topic model
docker-compose exec api python ml/models/train_topics.py \
  --sample-size 100000 --n-topics 60

# Evaluate new model
docker-compose exec api python ml/models/evaluate_topics.py \
  --reference-model models/bertopic_v1

# If coherence improves >5%, promote
docker-compose exec api python ml/models/register_topic_model.py \
  --version new --mlflow-uri http://mlflow:5000

# If degraded, rollback
docker-compose exec api python ml/models/register_topic_model.py \
  --version previous --mlflow-uri http://mlflow:5000
```

### Prevention
- Monitor coherence score weekly
- Retrain if dataset grows >20% since last training
- Keep moving average of topic stability metric

---

## Runbook: High API Latency

**Alert**: `SlowAPILatency` (p95 > 1000ms)

### Symptoms
- Search queries take >1 second
- Timeout errors in logs
- CPU/memory usage high on API pod

### Diagnosis
```bash
# Check slow queries (from Postgres logs)
docker-compose logs postgres | grep -i "duration" | tail -20

# Identify slow endpoint
docker-compose logs api | grep "latency" | tail -20

# Check database load
docker-compose exec postgres psql -U postgres -d patent_radar -c \
  "SELECT query, calls, mean_time FROM pg_stat_statements \
   ORDER BY mean_time DESC LIMIT 10;"

# Check index usage
docker-compose exec postgres psql -U postgres -d patent_radar -c \
  "SELECT schemaname, tablename, indexname, idx_scan \
   FROM pg_stat_user_indexes WHERE idx_scan = 0;"
```

### Recovery
```bash
# Add missing indexes
docker-compose exec postgres psql -U postgres -d patent_radar -f \
  data/schemas/add_missing_indexes.sql

# Analyze query plans
docker-compose exec postgres psql -U postgres -d patent_radar -c \
  "EXPLAIN ANALYZE \
   SELECT * FROM patents \
   WHERE to_tsvector('english', title || ' ' || abstract) @@ \
   plainto_tsquery('english', 'quantum');"

# Increase connection pool
docker-compose down && \
  sed -i 's/max_connections=100/max_connections=500/' docker-compose.yml && \
  docker-compose up -d postgres && sleep 10

# Scale API replicas (if on k8s)
kubectl scale deployment api --replicas=5 -n patent-radar
```

### Prevention
- Profile API endpoints weekly
- Monitor slow_log in Prometheus
- Implement query timeouts (30s default)
- Cache frequently accessed results (Redis)

---

## Runbook: Database Disk Full

**Alert**: `HighDiskUsage` (>90%)

### Symptoms
- Ingestion fails with "no space left"
- Postgres logs show connection errors
- All services hang

### Diagnosis
```bash
# Check disk usage
docker-compose exec postgres df -h

# Check table sizes
docker-compose exec postgres psql -U postgres -d patent_radar -c \
  "SELECT schemaname, tablename, \
   pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size \
   FROM pg_tables ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;"

# Check Qdrant storage
du -sh /var/lib/docker/volumes/*qdrant*/

# Check MinIO storage
docker-compose exec minio mc du minio/patents/
```

### Recovery
```bash
# Option 1: Archive old patents to S3
docker-compose exec postgres psql -U postgres -d patent_radar -c \
  "SELECT * FROM patents WHERE publication_date < NOW() - INTERVAL '2 years' \
   INTO OUTFILE '/tmp/old_patents.csv';"

# Copy to MinIO
docker-compose exec api python -c \
  "import boto3; \
   s3 = boto3.client('s3', endpoint_url='http://minio:9000'); \
   s3.upload_file('/tmp/old_patents.csv', 'patents', 'archive/old_patents.csv')"

# Delete from Postgres
docker-compose exec postgres psql -U postgres -d patent_radar -c \
  "DELETE FROM patents WHERE publication_date < NOW() - INTERVAL '2 years';"

# Vacuum
docker-compose exec postgres psql -U postgres -d patent_radar -c "VACUUM FULL ANALYZE;"

# Option 2: Increase disk allocation
# On macOS: Docker Desktop → Preferences → Disk image size
# On Linux: Extend LVM or increase bind mount size
```

### Prevention
- Monitor `disk_free_bytes` Prometheus metric
- Set retention policy: delete patents >3 years old monthly
- Archive to S3 before deletion

---

## Runbook: Model Drift Detected

**Alert**: Evidently AI drift detector fires

### Symptoms
- Novelty scores shifting lower/higher
- Topic assignments becoming less stable
- Alert precision drops

### Diagnosis
```bash
# Check drift metrics
curl http://localhost:9090/api/v1/query?query=model_drift_detected

# Inspect feature distributions
docker-compose exec api python ml/models/drift_detector.py \
  --baseline models/baseline_features.pkl \
  --current current_features.pkl

# Compare predictions
docker-compose exec api python -c \
  "from ml.models.ml_services import NoveltyScorer; \
   scorer = NoveltyScorer(); \
   historical = [scores from month ago]; \
   current = [scores this month]; \
   print(f'Mean shift: {np.mean(current) - np.mean(historical)}')"
```

### Recovery
```bash
# Option 1: Retrain novelty model
docker-compose exec api python ml/models/train_novelty.py \
  --historical-cutoff-weeks 52

# Option 2: Manual inspection
docker-compose exec postgres psql -U postgres -d patent_radar -c \
  "SELECT novelty_score, COUNT(*) FROM patents \
   WHERE novelty_scored_at > NOW() - INTERVAL '7 days' \
   GROUP BY ROUND(novelty_score, 1) ORDER BY novelty_score;"

# Option 3: Disable scoring temporarily
docker-compose exec api python -c \
  "import os; os.environ['ENABLE_NOVELTY_SCORING'] = 'false'"

# Investigate root cause
# - Did data distribution change? (new CPC codes, new assignees)
# - Did model assumptions break? (retraining needed)
# - Is it expected seasonality? (Q4 surge in filings)
```

### Prevention
- Check drift weekly
- Retrain models if Wasserstein distance >0.1
- Monitor baseline feature statistics monthly

---

## Runbook: Incident: Zero Alerts Generated for a Week

**Symptom**: Alert delivery stopped; watchlists not triggering

### Root Cause Analysis
1. Check if any accelerating trends exist
   ```bash
   docker-compose exec postgres psql -U postgres -d patent_radar -c \
     "SELECT COUNT(*) FROM cpc_codes WHERE trend_acceleration > 2.0;"
   ```

2. Check if thresholds are too strict
   ```bash
   docker-compose exec postgres psql -U postgres -d patent_radar -c \
     "SELECT alert_threshold_z_score, alert_threshold_confidence FROM watchlists;"
   ```

3. Check delivery pipeline
   ```bash
   docker-compose logs celery | grep "send_watchlist_digest"
   ```

### Recovery
1. Investigate data stagnation (no trending topics in a week = ok)
2. Lower thresholds if too conservative: `ALTER TABLE watchlists SET alert_threshold_z_score = 1.5`
3. Manually send digest: `celery -A tasks call send_watchlist_digest --args='["watchlist_id"]'`
4. Review alert precision: is lower alert rate due to false positives being fixed?

