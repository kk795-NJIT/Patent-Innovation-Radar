#!/usr/bin/env python3
"""
Train BERTopic model on patent abstracts and generate topic assignments.
Stores results in PostgreSQL topics and topic_assignments tables.
"""

import os
import sys
import logging
import numpy as np
import pickle
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_values

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from bertopic import BERTopic
    from sentence_transformers import SentenceTransformer
except ImportError as e:
    logger.error(f"❌ Missing dependency: {e}")
    logger.error("Install with: pip install bertopic sentence-transformers")
    sys.exit(1)

def connect_database():
    """Connect to PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "patent_radar"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres")
        )
        logger.info("✅ Connected to PostgreSQL")
        return conn
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        raise

def get_patent_abstracts(conn, limit=None):
    """Fetch patent abstracts from database."""
    try:
        cur = conn.cursor()
        query = """
            SELECT patent_id, abstract, title
            FROM patents
            WHERE abstract IS NOT NULL AND abstract != ''
            ORDER BY filing_date DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        
        cur.execute(query)
        results = cur.fetchall()
        
        patent_ids = [r[0] for r in results]
        abstracts = [r[1] or r[2] for r in results]  # Use abstract or title
        
        logger.info(f"📊 Loaded {len(abstracts)} patent abstracts")
        return patent_ids, abstracts
    except Exception as e:
        logger.error(f"❌ Error fetching abstracts: {e}")
        raise

def train_bertopic_model(abstracts, num_topics=20):
    """Train BERTopic model."""
    try:
        logger.info(f"📦 Loading embedding model...")
        embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        
        logger.info(f"🤖 Training BERTopic with {num_topics} topics...")
        
        topic_model = BERTopic(
            language="english",
            embedding_model=embedding_model,
            n_gram_range=(1, 2),
            min_topic_size=10,
            nr_topics=num_topics
        )
        
        # Generate embeddings
        logger.info("📝 Generating embeddings...")
        embeddings = embedding_model.encode(abstracts, show_progress_bar=True)
        
        # Fit model
        logger.info("🎯 Fitting topic model...")
        topics, probs = topic_model.fit_transform(abstracts, embeddings)
        
        logger.info(f"✅ Model trained with {topic_model.get_topic_info().shape[0]} topics")
        logger.info(f"   Topic info shape: {topic_model.get_topic_info()}")
        
        return topic_model, topics, probs
    except Exception as e:
        logger.error(f"❌ Training failed: {e}")
        raise

def extract_topic_info(topic_model):
    """Extract topic information from model."""
    try:
        topic_info = topic_model.get_topic_info()
        
        topics_data = []
        for idx, row in topic_info.iterrows():
            topic_id = row['Topic']
            if topic_id == -1:
                continue  # Skip outliers
            
            # Get top words
            words = topic_model.get_topic(topic_id)
            if words:
                top_words = ", ".join([f"{word}({score:.2f})" for word, score in words[:5]])
            else:
                top_words = "N/A"
            
            topics_data.append({
                "topic_id": int(topic_id),
                "name": f"Topic {topic_id}",
                "keywords": top_words,
                "count": int(row['Count']),
                "created_at": datetime.now()
            })
        
        logger.info(f"✅ Extracted {len(topics_data)} topics")
        return topics_data
    except Exception as e:
        logger.error(f"❌ Error extracting topics: {e}")
        raise

def store_topics(conn, topics_data):
    """Store topics in database."""
    try:
        cur = conn.cursor()
        
        # Delete existing topics
        cur.execute("DELETE FROM topics WHERE model_version = 'v1'")
        
        query = """
            INSERT INTO topics (topic_id, name, keywords, count, model_version, created_at)
            VALUES %s
        """
        values = [
            (t["topic_id"], t["name"], t["keywords"], t["count"], "v1", t["created_at"])
            for t in topics_data
        ]
        execute_values(cur, query, values)
        conn.commit()
        
        logger.info(f"✅ Stored {len(topics_data)} topics")
    except Exception as e:
        logger.error(f"❌ Error storing topics: {e}")
        conn.rollback()
        raise

def store_topic_assignments(conn, patent_ids, topics, probs):
    """Store topic assignments for patents."""
    try:
        cur = conn.cursor()
        
        # Delete existing assignments
        cur.execute("DELETE FROM topic_assignments")
        
        values = []
        for patent_id, topic_id, prob in zip(patent_ids, topics, probs):
            if topic_id >= 0:  # Skip outliers (-1 topics)
                # Get max probability for this patent's assignment
                max_prob = float(np.max(prob[prob >= 0]))
                values.append((patent_id, int(topic_id), max_prob))
        
        query = """
            INSERT INTO topic_assignments (patent_id, topic_id, confidence)
            VALUES %s
        """
        execute_values(cur, query, values, page_size=100)
        conn.commit()
        
        logger.info(f"✅ Stored {len(values)} topic assignments")
    except Exception as e:
        logger.error(f"❌ Error storing assignments: {e}")
        conn.rollback()
        raise

def save_model(topic_model, path="models/bertopic_model"):
    """Save trained model to disk."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        topic_model.save(path)
        logger.info(f"✅ Model saved to {path}")
    except Exception as e:
        logger.error(f"❌ Error saving model: {e}")

def verify_topics(conn):
    """Verify topics were stored."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM topics")
        topic_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM topic_assignments")
        assignment_count = cur.fetchone()[0]
        
        logger.info("\n" + "="*60)
        logger.info("📊 TOPICS VERIFICATION")
        logger.info("="*60)
        logger.info(f"  Topics in DB: {topic_count}")
        logger.info(f"  Assignments in DB: {assignment_count}")
        logger.info("="*60)
        
        return topic_count > 0 and assignment_count > 0
    except Exception as e:
        logger.error(f"❌ Verification failed: {e}")
        return False

def main():
    """Main topic modeling script."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Train BERTopic model")
    parser.add_argument("--limit", type=int, default=None, help="Limit abstracts")
    parser.add_argument("--topics", type=int, default=20, help="Number of topics")
    parser.add_argument("--save-model", action="store_true", help="Save model to disk")
    args = parser.parse_args()
    
    logger.info("\n" + "="*60)
    logger.info("🎯 BERTOPIC MODEL TRAINER")
    logger.info("="*60)
    
    try:
        # Connect
        conn = connect_database()
        
        # Load abstracts
        patent_ids, abstracts = get_patent_abstracts(conn, limit=args.limit)
        
        if len(abstracts) < 100:
            logger.error("❌ Need at least 100 abstracts for meaningful topic modeling")
            sys.exit(1)
        
        # Train model
        logger.info(f"\n🤖 Training BERTopic model with {args.topics} topics...")
        topic_model, topics, probs = train_bertopic_model(abstracts, args.topics)
        
        # Extract and store topics
        logger.info("\n💾 Storing topics...")
        topics_data = extract_topic_info(topic_model)
        store_topics(conn, topics_data)
        
        # Store assignments
        logger.info("💾 Storing assignments...")
        store_topic_assignments(conn, patent_ids, topics, probs)
        
        # Save model if requested
        if args.save_model:
            save_model(topic_model)
        
        # Verify
        verify_topics(conn)
        
        conn.close()
        
        logger.info("\n✅ TOPIC MODELING COMPLETED!")
        logger.info("="*60)
        logger.info("\nNext steps:")
        logger.info("1. Compute novelty scores: python scripts/compute_novelty.py")
        logger.info("2. View topics:            curl http://localhost:8000/topics")
        logger.info("="*60 + "\n")
        
    except Exception as e:
        logger.error(f"\n❌ SCRIPT FAILED: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
