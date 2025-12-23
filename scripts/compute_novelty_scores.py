#!/usr/bin/env python
"""
Compute novelty scores for seeded patents using a mock LightGBM model.
Novelty scoring based on:
- Citation count (older patents with fewer citations = higher novelty uncertainty)
- Claims complexity (more claims = potentially more novel aspects)
- Time decay (newer patents = higher novelty)
- Topic diversity (patents covering multiple topics = higher novelty)
"""

import os
import sys
import logging
from datetime import datetime, timedelta
import numpy as np
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://patent_user:patent_password@localhost:5432/patent_radar')


def get_patent_features(engine):
    """Extract features from patents for novelty scoring."""
    with engine.connect() as conn:
        # Create table if it doesn't exist
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS novelty_scores (
                patent_id TEXT PRIMARY KEY,
                novelty_score FLOAT NOT NULL,
                confidence FLOAT NOT NULL,
                computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (patent_id) REFERENCES patents(patent_id)
            )
        """))
        conn.commit()
        
        query = text("""
            SELECT 
                p.patent_id,
                p.publication_date,
                p.num_claims,
                p.num_citations,
                COUNT(DISTINCT ta.topic_id) as num_topics,
                COUNT(DISTINCT pa.assignee_id) as num_assignees
            FROM patents p
            LEFT JOIN patent_assignees pa ON p.patent_id = pa.patent_id
            LEFT JOIN topic_assignments ta ON p.patent_id = ta.patent_id
            WHERE p.patent_id NOT IN (SELECT patent_id FROM novelty_scores)
            GROUP BY p.patent_id, p.publication_date, p.num_claims, p.num_citations
            ORDER BY p.patent_id
        """)
        result = conn.execute(query)
        return result.fetchall()


def compute_novelty_score(patent_row):
    """
    Compute novelty score (0-1) for a patent using mock features.
    
    Features:
    - Recency: Patents from recent years score higher (newer = more likely to be novel)
    - Claims Complexity: More claims suggest more novel technical aspects
    - Citation Rarity: Patents with fewer backward citations in early years score higher
    - Topic Diversity: Patents spanning multiple topics score higher
    """
    patent_id, pub_date, num_claims, num_citations, num_topics, num_assignees = patent_row
    
    # Parse publication date
    if isinstance(pub_date, str):
        pub_date = datetime.fromisoformat(pub_date)
    elif isinstance(pub_date, type(None)):
        pub_date = datetime.now() - timedelta(days=365)  # Default to 1 year ago
    elif hasattr(pub_date, 'isoformat'):
        # Convert date to datetime if needed
        if not isinstance(pub_date, datetime):
            pub_date = datetime.combine(pub_date, datetime.min.time())
    
    # Feature 1: Recency (newer = more novel, 0-1)
    # Assume patents from last 5 years are "recent"
    today = datetime.now()
    years_old = (today - pub_date).days / 365.25
    recency_score = max(0, 1 - (years_old / 5))  # decay over 5 years
    
    # Feature 2: Claims Complexity (more claims = higher novelty potential)
    # Normalize to 0-1 (assume max 100 claims typical)
    complexity_score = min(1.0, num_claims / 100) if num_claims else 0.3
    
    # Feature 3: Citation Rarity (fewer early citations = lower certainty, potentially higher novelty)
    # Patents with few citations in their first 2 years could be truly novel or niche
    citation_score = 1.0 if num_citations < 5 else max(0.3, 1 - (num_citations / 50))
    
    # Feature 4: Topic Diversity (patents in multiple topics are more cross-cutting)
    diversity_score = min(1.0, num_topics / 5) if num_topics else 0.4
    
    # Feature 5: Assignee Diversity (multiple assignees = more interest/collaboration)
    assignee_score = min(1.0, num_assignees / 3) if num_assignees else 0.4
    
    # Weighted ensemble (mock LightGBM approximation)
    # Weights learned from training data (mock values)
    novelty_score = (
        0.30 * recency_score +          # Newer patents weighted heavily
        0.25 * complexity_score +        # Complex patents more likely novel
        0.20 * citation_score +          # Citation patterns matter
        0.15 * diversity_score +         # Cross-topic patents valued
        0.10 * assignee_score            # Collaborative patents interesting
    )
    
    # Confidence in the score (0-1)
    # High confidence if we have good data; lower if sparse
    confidence = min(
        1.0,
        (num_claims / 50) * (num_citations / 10) * (num_topics / 2)
    )
    confidence = max(0.3, confidence)  # At least 0.3 confidence baseline
    
    return float(novelty_score), float(confidence)


def insert_novelty_scores(engine, patent_data, batch_size=100):
    """Insert computed novelty scores into database."""
    if not patent_data:
        logger.info("No patents to score.")
        return 0
    
    try:
        with engine.connect() as conn:
            # Insert scores in batches
            for i in range(0, len(patent_data), batch_size):
                batch = patent_data[i:i + batch_size]
                
                insert_query = text("""
                    INSERT INTO novelty_scores (patent_id, novelty_score, confidence, computed_at)
                    VALUES (:patent_id, :novelty_score, :confidence, :computed_at)
                    ON CONFLICT (patent_id) DO UPDATE SET
                        novelty_score = EXCLUDED.novelty_score,
                        confidence = EXCLUDED.confidence,
                        computed_at = EXCLUDED.computed_at
                """)
                
                for patent_id, novelty_score, confidence in batch:
                    conn.execute(insert_query, {
                        "patent_id": patent_id,
                        "novelty_score": novelty_score,
                        "confidence": confidence,
                        "computed_at": datetime.now()
                    })
                
                conn.commit()
                logger.info(f"Inserted {min(batch_size, len(batch))} novelty scores")
        
        return len(patent_data)
    
    except Exception as e:
        logger.error(f"Error inserting novelty scores: {e}")
        raise


def verify_novelty_scores(engine):
    """Verify novelty scores were computed correctly."""
    with engine.connect() as conn:
        # Count scores
        count_query = text("SELECT COUNT(*) as count FROM novelty_scores")
        count = conn.execute(count_query).scalar()
        
        # Statistics
        stats_query = text("""
            SELECT 
                COUNT(*) as total,
                AVG(novelty_score) as avg_score,
                MIN(novelty_score) as min_score,
                MAX(novelty_score) as max_score,
                AVG(confidence) as avg_confidence
            FROM novelty_scores
        """)
        stats = conn.execute(stats_query).fetchone()
        
        logger.info(f"✅ Novelty Scores Summary:")
        logger.info(f"   Total scores computed: {count}")
        if stats:
            logger.info(f"   Average novelty score: {stats[1]:.3f}")
            logger.info(f"   Score range: {stats[2]:.3f} - {stats[3]:.3f}")
            logger.info(f"   Average confidence: {stats[4]:.3f}")
        
        # Top 5 most novel patents
        top_query = text("""
            SELECT p.patent_id, p.publication_number, p.title, ns.novelty_score, ns.confidence
            FROM novelty_scores ns
            JOIN patents p ON ns.patent_id = p.patent_id
            ORDER BY ns.novelty_score DESC
            LIMIT 5
        """)
        top_patents = conn.execute(top_query).fetchall()
        
        logger.info(f"\n   🏆 Top 5 Most Novel Patents:")
        for i, row in enumerate(top_patents, 1):
            patent_id, pub_number, title, score, conf = row
            logger.info(f"      {i}. [{pub_number}] {title[:50]}...")
            logger.info(f"         Novelty: {score:.3f}, Confidence: {conf:.3f}")
        
        return count, stats


def main():
    """Main execution."""
    logger.info("🚀 Starting novelty scoring computation...")
    
    try:
        # Connect to database
        engine = create_engine(DATABASE_URL)
        logger.info(f"✅ Connected to database: {DATABASE_URL}")
        
        # Get unscored patents
        logger.info("📊 Extracting patent features...")
        patent_data = get_patent_features(engine)
        logger.info(f"   Found {len(patent_data)} patents to score")
        
        if not patent_data:
            logger.info("   No new patents to score (all already have scores)")
            verify_novelty_scores(engine)
            return
        
        # Compute novelty scores
        logger.info("🔬 Computing novelty scores...")
        scored_patents = []
        for i, patent_row in enumerate(patent_data):
            novelty_score, confidence = compute_novelty_score(patent_row)
            patent_id = patent_row[0]
            scored_patents.append((patent_id, novelty_score, confidence))
            
            if (i + 1) % 100 == 0:
                logger.info(f"   Scored {i + 1}/{len(patent_data)} patents...")
        
        logger.info(f"✅ Computed {len(scored_patents)} novelty scores")
        
        # Insert into database
        logger.info("💾 Inserting scores into PostgreSQL...")
        count = insert_novelty_scores(engine, scored_patents)
        logger.info(f"✅ Inserted {count} novelty scores")
        
        # Verify
        verify_novelty_scores(engine)
        
        logger.info("\n✨ Novelty scoring complete!")
    
    except Exception as e:
        logger.error(f"❌ Error during novelty scoring: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
