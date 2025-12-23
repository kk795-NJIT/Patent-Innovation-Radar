"""
Patent + Innovation Radar: FastAPI Backend
Core API for search, semantic search, watchlists, alerts, and reports.
"""

from fastapi import FastAPI, HTTPException, Query, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timedelta
from uuid import UUID
import logging
import os
from contextlib import asynccontextmanager

from sqlalchemy import create_engine, text, func
from sqlalchemy.orm import sessionmaker, Session
import qdrant_client
from qdrant_client.models import PointStruct, VectorParams, Distance

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/patent_radar")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

# Qdrant setup
qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
qdrant_client = qdrant_client.QdrantClient(url=qdrant_url)

# ============================================================================
# Pydantic Models
# ============================================================================

class PatentSearchResult(BaseModel):
    patent_id: str
    title: str
    abstract: Optional[str]
    publication_date: str
    filing_date: str
    primary_cpc_code: Optional[str]
    num_claims: Optional[int]
    num_citations: int
    novelty_score: Optional[float]
    first_assignee_id: Optional[str]


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., description="Text query (abstract, claims, title)")
    limit: int = Field(10, ge=1, le=100)
    threshold: float = Field(0.6, ge=0.0, le=1.0)


class TopicSchema(BaseModel):
    topic_id: int
    name: str
    num_patents: int
    top_keywords: List[str]
    coherence_score: Optional[float]


class TrendSchema(BaseModel):
    topic_id: Optional[int]
    cpc_code: Optional[str]
    name: str
    num_patents_90d: int
    trend_acceleration: float
    z_score: float


class WatchlistCreate(BaseModel):
    user_id: str
    name: str
    assignee_ids: Optional[List[str]] = []
    cpc_codes: Optional[List[str]] = []
    topic_ids: Optional[List[int]] = []
    keywords: Optional[List[str]] = []
    digest_frequency: str = "weekly"
    email_addresses: Optional[List[str]] = []


class WatchlistSchema(WatchlistCreate):
    watchlist_id: UUID
    is_active: bool
    created_at: datetime


class AlertSchema(BaseModel):
    alert_id: UUID
    alert_type: str
    triggered_on: str
    triggered_value: str
    metric_value: float
    confidence: float
    description: str
    evidence_patents: List[str]
    status: str
    created_at: datetime


class ReportSchema(BaseModel):
    report_id: UUID
    report_type: str
    title: str
    executive_summary: str
    created_at: datetime


# ============================================================================
# Lifespan Handler
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown logic."""
    logger.info("App startup")
    yield
    logger.info("App shutdown")


app = FastAPI(
    title="Patent + Innovation Radar API",
    description="Intelligence platform for patent trends and competitive moves",
    version="1.0.0",
    lifespan=lifespan
)


# ============================================================================
# Dependencies
# ============================================================================

def get_db():
    """Database session dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# Search Endpoints
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/patents/search", response_model=List[PatentSearchResult])
async def search_patents(
    q: str = Query(..., description="Keyword search query"),
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Search patents by keyword in title/abstract.
    Uses PostgreSQL full-text search.
    """
    try:
        # Simple keyword search
        query = """
        SELECT 
            patent_id, title, abstract, publication_date, filing_date,
            primary_cpc_code, num_claims, num_citations, novelty_score, first_assignee_id
        FROM patents
        WHERE 
            to_tsvector('english', title || ' ' || COALESCE(abstract, ''))
            @@ plainto_tsquery('english', :query)
        ORDER BY publication_date DESC
        LIMIT :limit OFFSET :offset
        """
        
        results = db.execute(text(query), {"query": q, "limit": limit, "offset": offset})
        patents = [
            PatentSearchResult(
                patent_id=r[0],
                title=r[1],
                abstract=r[2],
                publication_date=str(r[3]),
                filing_date=str(r[4]),
                primary_cpc_code=r[5],
                num_claims=r[6],
                num_citations=r[7],
                novelty_score=r[8],
                first_assignee_id=r[9]
            )
            for r in results
        ]
        return patents
    
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/patents/semantic-search", response_model=List[PatentSearchResult])
async def semantic_search(
    request: SemanticSearchRequest,
    db: Session = Depends(get_db)
):
    """
    Semantic search using embeddings.
    Requires embeddings to be precomputed in Qdrant.
    """
    try:
        # This is a placeholder; in production, you'd embed the query and search Qdrant
        # For now, return top patents by novelty score
        
        query = """
        SELECT 
            patent_id, title, abstract, publication_date, filing_date,
            primary_cpc_code, num_claims, num_citations, novelty_score, first_assignee_id
        FROM patents
        WHERE novelty_score IS NOT NULL
        ORDER BY novelty_score DESC, publication_date DESC
        LIMIT :limit
        """
        
        results = db.execute(text(query), {"limit": request.limit})
        patents = [
            PatentSearchResult(
                patent_id=r[0],
                title=r[1],
                abstract=r[2],
                publication_date=str(r[3]),
                filing_date=str(r[4]),
                primary_cpc_code=r[5],
                num_claims=r[6],
                num_citations=r[7],
                novelty_score=r[8],
                first_assignee_id=r[9]
            )
            for r in results
        ]
        return patents
    
    except Exception as e:
        logger.error(f"Semantic search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Topic Endpoints
# ============================================================================

@app.get("/topics", response_model=List[TopicSchema])
async def list_topics(
    search: Optional[str] = None,
    min_patents: int = Query(10, ge=1),
    db: Session = Depends(get_db)
):
    """List all topics."""
    try:
        query = "SELECT topic_id, name, num_patents, top_keywords, coherence_score FROM topics WHERE num_patents >= :min_patents"
        params = {"min_patents": min_patents}
        
        if search:
            query += " AND name ILIKE :search"
            params["search"] = f"%{search}%"
        
        query += " ORDER BY num_patents DESC"
        
        results = db.execute(text(query), params)
        topics = [
            TopicSchema(
                topic_id=r[0],
                name=r[1],
                num_patents=r[2],
                top_keywords=r[3] or [],
                coherence_score=r[4]
            )
            for r in results
        ]
        return topics
    
    except Exception as e:
        logger.error(f"List topics error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/topics/{topic_id}", response_model=TopicSchema)
async def get_topic(
    topic_id: int,
    db: Session = Depends(get_db)
):
    """Get details for a specific topic."""
    try:
        result = db.execute(
            text("SELECT topic_id, name, num_patents, top_keywords, coherence_score FROM topics WHERE topic_id = :id"),
            {"id": topic_id}
        ).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Topic not found")
        
        return TopicSchema(
            topic_id=result[0],
            name=result[1],
            num_patents=result[2],
            top_keywords=result[3] or [],
            coherence_score=result[4]
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get topic error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Trend Endpoints
# ============================================================================

@app.get("/trends", response_model=List[TrendSchema])
async def get_trends(
    period_days: int = Query(90, ge=7, le=365),
    min_z_score: float = Query(1.5, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get accelerating trends (topics with rising filing rates)."""
    try:
        query = """
        SELECT topic_id, NULL as cpc_code, name, num_patents, COALESCE(trend_acceleration, 0) as trend_acc
        FROM topics
        WHERE trend_acceleration IS NOT NULL AND trend_acceleration >= :z_score
        ORDER BY trend_acceleration DESC
        LIMIT :limit
        """
        
        results = db.execute(text(query), {"z_score": min_z_score, "limit": limit})
        trends = [
            TrendSchema(
                topic_id=r[0],
                cpc_code=r[1],
                name=r[2],
                num_patents_90d=r[3],
                trend_acceleration=r[4],
                z_score=r[4]
            )
            for r in results
        ]
        return trends
    
    except Exception as e:
        logger.error(f"Get trends error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Watchlist Endpoints
# ============================================================================

@app.post("/watchlists", response_model=WatchlistSchema)
async def create_watchlist(
    watchlist: WatchlistCreate,
    db: Session = Depends(get_db)
):
    """Create a new watchlist."""
    try:
        stmt = text("""
        INSERT INTO watchlists (
            user_id, name, assignee_ids, cpc_codes, topic_ids, keywords,
            digest_frequency, email_addresses
        ) VALUES (
            :user_id, :name, :assignee_ids, :cpc_codes, :topic_ids, :keywords,
            :freq, :emails
        )
        RETURNING watchlist_id, is_active, created_at
        """)
        
        result = db.execute(stmt, {
            "user_id": watchlist.user_id,
            "name": watchlist.name,
            "assignee_ids": watchlist.assignee_ids,
            "cpc_codes": watchlist.cpc_codes,
            "topic_ids": watchlist.topic_ids,
            "keywords": watchlist.keywords,
            "freq": watchlist.digest_frequency,
            "emails": watchlist.email_addresses
        }).fetchone()
        
        db.commit()
        
        return WatchlistSchema(
            watchlist_id=result[0],
            user_id=watchlist.user_id,
            name=watchlist.name,
            assignee_ids=watchlist.assignee_ids,
            cpc_codes=watchlist.cpc_codes,
            topic_ids=watchlist.topic_ids,
            keywords=watchlist.keywords,
            digest_frequency=watchlist.digest_frequency,
            email_addresses=watchlist.email_addresses,
            is_active=result[1],
            created_at=result[2]
        )
    
    except Exception as e:
        logger.error(f"Create watchlist error: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/watchlists/{user_id}", response_model=List[WatchlistSchema])
async def list_watchlists(
    user_id: str,
    db: Session = Depends(get_db)
):
    """List all watchlists for a user."""
    try:
        results = db.execute(
            text("""
            SELECT watchlist_id, user_id, name, assignee_ids, cpc_codes, topic_ids,
                   keywords, digest_frequency, email_addresses, is_active, created_at
            FROM watchlists
            WHERE user_id = :user_id AND is_active = TRUE
            ORDER BY created_at DESC
            """),
            {"user_id": user_id}
        )
        
        watchlists = [
            WatchlistSchema(
                watchlist_id=r[0],
                user_id=r[1],
                name=r[2],
                assignee_ids=r[3],
                cpc_codes=r[4],
                topic_ids=r[5],
                keywords=r[6],
                digest_frequency=r[7],
                email_addresses=r[8],
                is_active=r[9],
                created_at=r[10]
            )
            for r in results
        ]
        return watchlists
    
    except Exception as e:
        logger.error(f"List watchlists error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Alert Endpoints
# ============================================================================

@app.get("/watchlists/{watchlist_id}/alerts", response_model=List[AlertSchema])
async def get_alerts(
    watchlist_id: UUID,
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get alerts for a watchlist."""
    try:
        query = """
        SELECT alert_id, alert_type, triggered_on, triggered_value, metric_value,
               confidence, description, evidence_patents, status, created_at
        FROM alerts
        WHERE watchlist_id = :watchlist_id
        """
        params = {"watchlist_id": str(watchlist_id)}
        
        if status:
            query += " AND status = :status"
            params["status"] = status
        
        query += " ORDER BY created_at DESC LIMIT :limit"
        params["limit"] = limit
        
        results = db.execute(text(query), params)
        
        alerts = [
            AlertSchema(
                alert_id=r[0],
                alert_type=r[1],
                triggered_on=r[2],
                triggered_value=r[3],
                metric_value=r[4],
                confidence=r[5],
                description=r[6],
                evidence_patents=r[7] or [],
                status=r[8],
                created_at=r[9]
            )
            for r in results
        ]
        return alerts
    
    except Exception as e:
        logger.error(f"Get alerts error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Report Endpoints
# ============================================================================

@app.get("/reports/{report_id}", response_model=ReportSchema)
async def get_report(
    report_id: UUID,
    db: Session = Depends(get_db)
):
    """Get a specific report."""
    try:
        result = db.execute(
            text("""
            SELECT report_id, report_type, title, executive_summary, created_at
            FROM reports
            WHERE report_id = :id
            """),
            {"id": str(report_id)}
        ).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Report not found")
        
        return ReportSchema(
            report_id=result[0],
            report_type=result[1],
            title=result[2],
            executive_summary=result[3],
            created_at=result[4]
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
