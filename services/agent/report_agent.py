"""
Patent + Innovation Radar: LangGraph Agent
Produces weekly "Threats & Opportunities" reports and handles MLOps incidents.
"""

import logging
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Annotated
from enum import Enum

from langgraph.graph import StateGraph, START, END
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import anthropic

logger = logging.getLogger(__name__)


# ============================================================================
# State & Types
# ============================================================================

class ReportMode(str, Enum):
    """Report generation modes."""
    WEEKLY_BRIEF = "weekly_brief"
    INCIDENT = "incident"
    DEEP_DIVE = "deep_dive"


class AgentState(BaseModel):
    """Agent state for report generation workflow."""
    
    # Input
    user_id: str
    watchlist_id: Optional[str] = None
    mode: ReportMode = ReportMode.WEEKLY_BRIEF
    
    # Processing
    raw_data: Dict = Field(default_factory=dict)  # Fetched patent/trend data
    analysis_notes: str = ""
    evidence_queries: List[str] = Field(default_factory=list)
    
    # Output
    report_title: str = ""
    executive_summary: str = ""
    emerging_topics: List[Dict] = Field(default_factory=list)
    key_patents: List[Dict] = Field(default_factory=list)
    competitor_moves: List[Dict] = Field(default_factory=list)
    watchlist_changes: List[Dict] = Field(default_factory=list)
    appendix_evidence: List[Dict] = Field(default_factory=list)
    
    # Metadata
    report_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    approval_required: bool = False
    approval_token: Optional[str] = None


# ============================================================================
# Database & Context
# ============================================================================

class ReportDataFetcher:
    """Fetches evidence data from database for report generation."""
    
    def __init__(self, db_url: str = os.getenv("DATABASE_URL")):
        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
    
    def fetch_emerging_topics(self, days: int = 7, limit: int = 5) -> List[Dict]:
        """Fetch emerging topics (accelerating filing rate)."""
        db = self.SessionLocal()
        try:
            query = text("""
            SELECT 
                t.topic_id, t.name, t.top_keywords,
                COUNT(DISTINCT ta.patent_id) as num_patents,
                COALESCE(t.trend_acceleration, 0) as acceleration
            FROM topics t
            LEFT JOIN topic_assignments ta ON t.topic_id = ta.topic_id
            LEFT JOIN patents p ON ta.patent_id = p.patent_id
            WHERE p.publication_date >= NOW() - INTERVAL ':days days'
            GROUP BY t.topic_id, t.name, t.top_keywords, t.trend_acceleration
            ORDER BY acceleration DESC, num_patents DESC
            LIMIT :limit
            """)
            
            results = db.execute(query, {"days": days, "limit": limit}).fetchall()
            
            topics = []
            for r in results:
                topics.append({
                    "topic_id": r[0],
                    "name": r[1],
                    "keywords": r[2] or [],
                    "num_patents": r[3],
                    "acceleration": float(r[4])
                })
            
            return topics
        
        finally:
            db.close()
    
    def fetch_novel_patents(self, days: int = 7, limit: int = 10) -> List[Dict]:
        """Fetch recently novel patents."""
        db = self.SessionLocal()
        try:
            query = text("""
            SELECT 
                p.patent_id, p.title, p.abstract,
                p.novelty_score, p.publication_date,
                a.name as assignee_name
            FROM patents p
            LEFT JOIN patent_assignees pa ON p.patent_id = pa.patent_id AND pa.position = 0
            LEFT JOIN assignees a ON pa.assignee_id = a.assignee_id
            WHERE p.publication_date >= NOW() - INTERVAL ':days days'
              AND p.novelty_score IS NOT NULL
            ORDER BY p.novelty_score DESC
            LIMIT :limit
            """)
            
            results = db.execute(query, {"days": days, "limit": limit}).fetchall()
            
            patents = []
            for r in results:
                patents.append({
                    "patent_id": r[0],
                    "title": r[1],
                    "abstract": r[2][:200] if r[2] else "",
                    "novelty_score": float(r[3]) if r[3] else 0,
                    "publication_date": str(r[4]),
                    "assignee": r[5]
                })
            
            return patents
        
        finally:
            db.close()
    
    def fetch_competitor_moves(self, watchlist_assignees: List[str], days: int = 7) -> List[Dict]:
        """Detect competitive moves: new CPC/topic entries."""
        if not watchlist_assignees:
            return []
        
        db = self.SessionLocal()
        try:
            # Find new CPC codes or topics entered by watched assignees
            query = text("""
            SELECT 
                a.assignee_id, a.name,
                p.primary_cpc_code,
                COUNT(*) as num_new_filings
            FROM patents p
            JOIN patent_assignees pa ON p.patent_id = pa.patent_id
            JOIN assignees a ON pa.assignee_id = a.assignee_id
            WHERE a.assignee_id = ANY(:assignee_ids)
              AND p.publication_date >= NOW() - INTERVAL ':days days'
            GROUP BY a.assignee_id, a.name, p.primary_cpc_code
            ORDER BY num_new_filings DESC
            """)
            
            results = db.execute(query, {
                "assignee_ids": watchlist_assignees,
                "days": days
            }).fetchall()
            
            moves = []
            for r in results:
                moves.append({
                    "assignee_id": r[0],
                    "assignee_name": r[1],
                    "cpc_code": r[2],
                    "num_filings": r[3]
                })
            
            return moves
        
        finally:
            db.close()


# ============================================================================
# Agent Tools (Runnable Functions)
# ============================================================================

def tool_fetch_evidence(state: AgentState) -> Command:
    """Tool: Fetch evidence data from database."""
    
    logger.info(f"Fetching evidence for user {state.user_id}...")
    
    fetcher = ReportDataFetcher()
    
    # Fetch data
    emerging_topics = fetcher.fetch_emerging_topics(days=7, limit=5)
    novel_patents = fetcher.fetch_novel_patents(days=7, limit=10)
    competitor_moves = fetcher.fetch_competitor_moves([], days=7)  # No watchlist provided
    
    # Store in state
    state.raw_data = {
        "emerging_topics": emerging_topics,
        "novel_patents": novel_patents,
        "competitor_moves": competitor_moves
    }
    
    state.evidence_queries = [
        "SELECT emerging topics (last 7 days, ranked by acceleration)",
        "SELECT novel patents (novelty_score DESC)",
        "SELECT competitor moves (CPC entries)"
    ]
    
    logger.info(f"Fetched evidence: {len(emerging_topics)} topics, {len(novel_patents)} patents, {len(competitor_moves)} moves")
    
    return Command(goto="analyze_evidence", update=state)


def tool_analyze_evidence(state: AgentState) -> Command:
    """Tool: Analyze evidence and extract insights."""
    
    logger.info("Analyzing evidence...")
    
    # Extract insights from raw data
    state.emerging_topics = state.raw_data.get("emerging_topics", [])[:5]
    state.key_patents = state.raw_data.get("novel_patents", [])[:10]
    state.competitor_moves = state.raw_data.get("competitor_moves", [])[:10]
    
    state.analysis_notes = f"""
    Analyzed {len(state.emerging_topics)} emerging topics.
    Identified {len(state.key_patents)} key novel patents.
    Detected {len(state.competitor_moves)} competitor moves.
    """
    
    return Command(goto="generate_report", update=state)


def tool_generate_report(state: AgentState) -> Command:
    """Tool: Generate structured report text using Claude."""
    
    logger.info("Generating report with Claude...")
    
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    # Prepare context for Claude
    context = f"""
    You are a patent intelligence analyst. Generate a professional weekly brief.
    
    Data:
    - Emerging Topics: {json.dumps(state.emerging_topics, indent=2)}
    - Key Patents: {json.dumps(state.key_patents, indent=2)}
    - Competitor Moves: {json.dumps(state.competitor_moves, indent=2)}
    
    Generate:
    1. Executive Summary (2-3 sentences)
    2. Key Threats (top 3 with evidence)
    3. Key Opportunities (top 3 with evidence)
    4. Recommended Actions
    
    Format as JSON.
    """
    
    try:
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            messages=[
                {"role": "user", "content": context}
            ]
        )
        
        report_text = message.content[0].text
        
        # Parse report (Claude returns JSON)
        try:
            report_json = json.loads(report_text)
            state.executive_summary = report_json.get("executive_summary", "")
            state.report_title = f"Weekly Patent Intelligence Brief - {datetime.now().strftime('%Y-%m-%d')}"
        except:
            state.executive_summary = report_text
            state.report_title = f"Weekly Patent Intelligence Brief - {datetime.now().strftime('%Y-%m-%d')}"
        
        logger.info("Report generated successfully")
    
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        state.executive_summary = "Report generation failed. Please check API credentials."
    
    return Command(goto="finalize_report", update=state)


def tool_finalize_report(state: AgentState) -> Command:
    """Tool: Format report and store in database."""
    
    logger.info("Finalizing report...")
    
    # Build appendix
    state.appendix_evidence = [
        {
            "type": "emerging_topic",
            "id": t["topic_id"],
            "name": t["name"],
            "reference": f"topic/{t['topic_id']}"
        }
        for t in state.emerging_topics
    ] + [
        {
            "type": "patent",
            "id": p["patent_id"],
            "title": p["title"],
            "reference": f"patent/{p['patent_id']}"
        }
        for p in state.key_patents
    ]
    
    # Store report in database
    db_url = os.getenv("DATABASE_URL")
    engine = create_engine(db_url)
    
    with engine.begin() as conn:
        import uuid
        report_id = str(uuid.uuid4())
        
        stmt = text("""
        INSERT INTO reports (
            report_id, user_id, report_type, title, executive_summary,
            emerging_topics, key_patents, competitor_moves,
            evidence_patents, evidence_queries,
            created_at, delivered_at
        ) VALUES (
            :report_id, :user_id, :report_type, :title, :summary,
            :topics, :patents, :moves,
            :evidence_patents, :evidence_queries,
            NOW(), NOW()
        )
        """)
        
        evidence_patent_ids = [p["patent_id"] for p in state.key_patents]
        
        conn.execute(stmt, {
            "report_id": report_id,
            "user_id": state.user_id,
            "report_type": state.mode.value,
            "title": state.report_title,
            "summary": state.executive_summary,
            "topics": json.dumps(state.emerging_topics),
            "patents": json.dumps(state.key_patents),
            "moves": json.dumps(state.competitor_moves),
            "evidence_patents": evidence_patent_ids,
            "evidence_queries": state.evidence_queries
        })
    
    state.report_id = report_id
    logger.info(f"Report finalized: {report_id}")
    
    return Command(goto=END, update=state)


# ============================================================================
# Graph Construction
# ============================================================================

def build_report_graph() -> StateGraph:
    """Build LangGraph workflow for report generation."""
    
    graph = StateGraph(AgentState)
    
    # Add nodes (tools)
    graph.add_node("fetch_evidence", tool_fetch_evidence)
    graph.add_node("analyze_evidence", tool_analyze_evidence)
    graph.add_node("generate_report", tool_generate_report)
    graph.add_node("finalize_report", tool_finalize_report)
    
    # Add edges
    graph.add_edge(START, "fetch_evidence")
    graph.add_edge("fetch_evidence", "analyze_evidence")
    graph.add_edge("analyze_evidence", "generate_report")
    graph.add_edge("generate_report", "finalize_report")
    
    return graph


# ============================================================================
# Public Agent Interface
# ============================================================================

class ReportAgent:
    """High-level interface for report generation."""
    
    def __init__(self):
        self.graph = build_report_graph().compile()
    
    def generate_weekly_brief(self, user_id: str, watchlist_id: Optional[str] = None) -> AgentState:
        """Generate a weekly intelligence brief."""
        
        initial_state = AgentState(
            user_id=user_id,
            watchlist_id=watchlist_id,
            mode=ReportMode.WEEKLY_BRIEF
        )
        
        logger.info(f"Starting weekly brief for user {user_id}...")
        
        result = self.graph.invoke(initial_state)
        
        logger.info(f"Completed report: {result.report_id}")
        return result
    
    def generate_incident_summary(self, incident_type: str, details: Dict) -> AgentState:
        """Generate incident summary (alert failure, data freshness drop, drift spike)."""
        
        initial_state = AgentState(
            user_id="system",
            mode=ReportMode.INCIDENT,
            analysis_notes=f"Incident: {incident_type}\nDetails: {json.dumps(details)}"
        )
        
        logger.info(f"Generating incident summary: {incident_type}")
        
        result = self.graph.invoke(initial_state)
        return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    agent = ReportAgent()
    
    # Example: generate weekly brief
    report = agent.generate_weekly_brief(user_id="analyst_001")
    print(f"Report ID: {report.report_id}")
    print(f"Title: {report.report_title}")
    print(f"Summary: {report.executive_summary[:200]}")
