# Patent + Innovation Radar: Product Specification

## Executive Summary

**Patent + Innovation Radar** is a production-grade intelligence system that detects emerging technology trends early, tracks competitor patent moves, and generates evidence-backed weekly "threats/opportunities" briefings. It's built for strategic decision-makers (VCs, corporate strategists, R&D leaders) who need defensible, patent-backed insights delivered weekly.

---

## 1. User Personas

### Persona 1: VC/Investment Partner (Jane)
- **Role**: Tech investor evaluating startups in deep tech, semiconductors, AI/ML
- **Goals**: Identify emerging technology clusters 6-12 months before market inflection; spot new entrants; assess competitive moats
- **Frustration**: Patent data is scattered; can't correlate filings with company trajectory; month-old trend reports are stale
- **Workflow**: Opens radar weekly → reviews "emerging topics" + "competitive moves" → clicks into assignees/patents → builds thesis

### Persona 2: Corporate Strategy / BD (Marcus)
- **Role**: Strategic business development at established tech company
- **Goals**: Monitor competitor R&D; identify M&A targets; stay ahead of disruption in core domain
- **Frustration**: Competitors filing in unfamiliar CPC codes; can't tell if it's meaningful or noise; needs cross-functional buy-in
- **Workflow**: Sets watchlist for 5 competitors + 10 CPC codes → daily alerts (material changes) → weekly digest → exports evidence for exec meeting

### Persona 3: R&D Technical Lead (Priya)
- **Role**: Head of R&D at hardware/deep tech startup
- **Goals**: Understand patent landscape before filing; find non-obvious prior art; collaborate with legal on novelty arguments
- **Frustration**: Patent search tools are archaic; can't explore topic clusters; no way to find "similar innovations across assignees"
- **Workflow**: Uploads draft claims → semantic search for similar patents → explores related topics → notes prior art risks

---

## 2. User Journeys

### Journey 1: Watchlist Creation → Weekly Brief → Deep Dive

1. **Setup**: Marcus logs in, clicks "New Watchlist"
   - Adds assignee "Nvidia" + "TSMC"
   - Adds CPC codes: H01L (semiconductors), G06F (computing)
   - Adds keyword: "quantum" + "3D memory"
   - System auto-suggests related topics: "quantum computing," "memory stacks"
   
2. **Weekly Brief (Every Monday 8 AM)**: Marcus receives email digest
   - Header: "Emerging Topics in Your Watchlist (Last 7 days)"
   - Section A: Top 5 emerging topics with patent counts, growth rate, novel patents
   - Section B: "Competitive Moves": Nvidia entered 3 new CPC co-occurrences (with confidence %, reason)
   - Section C: Key novel patents assigned to watchlist companies
   - Section D: Appendix with links to all source patents, queries used, statistical confidence

3. **Deep Dive**: Marcus clicks "Emerging Topic: Chiplet Integration"
   - Views: Topic definition, trend chart (12-month backfill), top 10 patents (with novelty scores)
   - Competitors in this topic: Intel, Samsung, TSMC, ARM (with filing counts)
   - Semantic neighbors: "3D interconnect," "chiplet design," "heterogeneous integration"
   - Export: List of patents as CSV with embeddings, assignees, dates

---

### Journey 2: Threat Detection & Incident Alert

1. **Baseline**: Priya has 5 CPC codes watched (her core domain)
2. **Alert Trigger**: This week, filing rate in one CPC code jumps 350% (vs. 12-month moving avg)
3. **System Action**: Immediately triggers "Material Change Alert"
   - Alert summary: "Acceleration detected in CPC H01M (batteries) — 47 filings (vs. 9-week avg of 13.4)"
   - Top new assignees: Tesla (+12 filings), Samsung (+8 filings), CATL (+6 filings)
   - Confidence: 87% (based on z-score significance test + seasonal adjustment)
   - Recommendation: Review top 10 novel patents in this surge
4. **Action**: Priya clicks through, filters to her competitors, exports patent lists

---

### Journey 3: Competitive Intelligence Graph

1. Jane enters Neo4j graph explorer mode
2. Starts with node: Assignee "OpenAI"
3. Expands: "Patents filed" → all patents assigned to OpenAI in last 24 months
4. Filters to CPC: G06N (AI/ML)
5. Expands: "Co-inventors" → discovers key inventors, their filing patterns
6. Expands: "Topic membership" → OpenAI's patents span 12 topics; heavily concentrated in "LLM foundations" + "multimodal learning"
7. Expands: "Citation graph" → which patent families cite OpenAI patents?
8. Exports: Node list, edge list for further analysis

---

## 3. MVP vs V1 vs V2 Scope

### MVP (Week 1-2: Minimum Viable Product)
**Goal**: Prove data pipeline + basic search + single weekly report

**Features**:
- ✅ PatentsView API ingestion (daily, 1000 patents/day delta)
- ✅ Postgres storage + basic schema
- ✅ Keyword search API
- ✅ Basic UI: search bar, patent list view
- ✅ Great Expectations validation (schema, nullability)
- ✅ Manual weekly report (CSV dump of top trends)

**Stack**: Python, Postgres, FastAPI (minimal endpoints), Streamlit (search UI), Great Expectations

**Out of scope**: Topic modeling, ML models, Neo4j, alerts, agents

---

### V1 (Week 2-4: Minimum Viable Intelligence)
**Goal**: Add semantic search, topic modeling, trend detection, watchlists, weekly agent report

**New Features**:
- ✅ Sentence-Transformers embeddings + Qdrant vector DB
- ✅ Semantic search API + "similar patents" endpoint
- ✅ BERTopic topic modeling + topic pages
- ✅ Trend acceleration detection (z-score based)
- ✅ Watchlists: assignee, CPC, keyword, topic
- ✅ Weekly email digest (Celery tasks)
- ✅ LangGraph agent: fetch evidence, write structured brief
- ✅ Novelty scoring (simple: embedding distance to historical neighbors)
- ✅ Neo4j: assignee-inventor-CPC graphs
- ✅ Material change alerts (threshold-based)
- ✅ Basic Kubeflow pipeline (ingest → validate → embed → score → update)
- ✅ Prometheus metrics + Grafana dashboards
- ✅ Docker Compose local dev

**Out of scope**: KServe, advanced SHAP explainability, seasonal modeling, cross-assignee adoption graphs

---

### V2 (Post-launch: Enterprise Features)
**Goal**: Production hardening, advanced analytics, ops automation

**New Features**:
- ✅ KServe InferenceServices (embedding model, novelty model)
- ✅ Advanced novelty: LightGBM model + SHAP + cite-based features
- ✅ Seasonal trend adjustment (LOESS smoothing)
- ✅ Competitive move detection: assignee-topic transition matrix + significance
- ✅ Graph analytics: PageRank, community detection (Louvain)
- ✅ Ops agent: auto-incident summaries on drift/freshness drops
- ✅ GitOps approval workflow (ArgoCD)
- ✅ Advanced RBAC (Keycloak) + API rate limiting
- ✅ Drift monitoring (Evidently AI) integrated into metrics
- ✅ ClickHouse for OLAP queries on large patent aggregations
- ✅ Helm + Kustomize k8s deployment
- ✅ Integration tests + load tests + regression tests

---

## 4. Success Metrics

| Metric | MVP | V1 | V2 |
|--------|-----|----|----|
| **Data Freshness** | < 24h lag | < 12h lag | < 6h lag |
| **Trend Precision** | N/A | 70% (emerging topics match future citations) | 80%+ |
| **API p95 Latency** | 500ms | 200ms | 100ms |
| **Alert Precision** | N/A | 75% (% of alerts leading to real decisions) | 85%+ |
| **System Uptime** | 95% | 99.0% | 99.5% |
| **Weekly Report Delivery** | Manual CSV | Automated email + API | Email + API + Slack + Internal portal |

---

## 5. Out of Scope (Explicitly)

- Real-time ingestion (batch daily is sufficient)
- Multi-language patent support (English only initially)
- Scientific publication tracking (patents only)
- Licensing analysis (filing intent only)
- Litigation/enforcement data (beyond citation patterns)
- White papers/blog aggregation

---

## Appendix: Glossary

- **Topic**: A BERTopic cluster of semantically related patents (e.g., "quantum error correction")
- **Trend Acceleration**: Week-over-week filing count growth in a topic, detected via z-score
- **Novelty Score**: 0-100 score indicating how "novel" a patent is vs. historical corpus (embeddings + citation patterns)
- **Competitive Move**: Assignee entering a new CPC code or topic with statistical significance
- **Material Change Alert**: Filing rate jump (>2σ) in a watched category, delivered within 2 hours
- **Watchlist**: User's saved set of assignees, CPC codes, topics, keywords for alert delivery

