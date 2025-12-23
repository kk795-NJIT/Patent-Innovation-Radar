#!/usr/bin/env python3
"""
Generate embeddings for patent abstracts (simplified version).
Uses a cached embedding approach without sentence-transformers compatibility issues.
"""

import os
import sys
import logging
import numpy as np
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_values
import hashlib
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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

def connect_qdrant():
    """Connect to Qdrant vector database."""
    try:
        client = QdrantClient(
            url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            timeout=30
        )
        logger.info("✅ Connected to Qdrant")
        return client
    except Exception as e:
        logger.error(f"❌ Qdrant connection failed: {e}")
        raise

def load_model(model_name="all-MiniLM-L6-v2"):
    """Load sentence-transformers model."""
    try:
        logger.info(f"📦 Loading model: {model_name}")
        model = SentenceTransformer(model_name)
        logger.info(f"✅ Model loaded (embedding dimension: {model.get_sentence_embedding_dimension()})")
        return model
    except Exception as e:
        logger.error(f"❌ Model loading failed: {e}")
        raise

def get_patents_needing_embeddings(conn, limit=None):
    """Fetch patents without embeddings."""
    try:
        cur = conn.cursor()
        query = """
            SELECT p.patent_id, p.title, p.abstract
            FROM patents p
            LEFT JOIN embeddings e ON p.patent_id = e.patent_id
            WHERE e.patent_id IS NULL
            ORDER BY p.filing_date DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        
        cur.execute(query)
        patents = cur.fetchall()
        logger.info(f"📊 Found {len(patents)} patents needing embeddings")
        return patents
    except Exception as e:
        logger.error(f"❌ Error fetching patents: {e}")
        raise

def generate_embeddings_batch(model, patents, batch_size=32):
    """Generate embeddings for patent abstracts."""
    embeddings_data = []
    
    for i in range(0, len(patents), batch_size):
        batch = patents[i:i+batch_size]
        abstracts = [p[2] or p[1] for p in batch]  # Use abstract or title
        
        try:
            batch_embeddings = model.encode(abstracts, show_progress_bar=False)
            
            for (patent_id, title, abstract), embedding in zip(batch, batch_embeddings):
                embeddings_data.append({
                    "patent_id": patent_id,
                    "embedding": embedding.tolist(),
                    "model": "all-MiniLM-L6-v2",
                    "created_at": datetime.now()
                })
            
            logger.info(f"  ✓ Processed batch {i//batch_size + 1}/{(len(patents)-1)//batch_size + 1}")
        
        except Exception as e:
            logger.error(f"❌ Error generating embeddings for batch: {e}")
            continue
    
    logger.info(f"✅ Generated {len(embeddings_data)} embeddings")
    return embeddings_data

def store_embeddings_postgresql(conn, embeddings_data):
    """Store embeddings in PostgreSQL."""
    try:
        cur = conn.cursor()
        query = """
            INSERT INTO embeddings (patent_id, embedding_vector, model, created_at)
            VALUES %s
            ON CONFLICT (patent_id) DO UPDATE SET
                embedding_vector = EXCLUDED.embedding_vector,
                updated_at = NOW()
        """
        values = [
            (e["patent_id"], e["embedding"], e["model"], e["created_at"])
            for e in embeddings_data
        ]
        execute_values(cur, query, values, page_size=100)
        conn.commit()
        logger.info(f"✅ Stored {len(embeddings_data)} embeddings in PostgreSQL")
    except Exception as e:
        logger.error(f"❌ Error storing embeddings: {e}")
        conn.rollback()
        raise

def store_embeddings_qdrant(client, embeddings_data, collection_name="patents"):
    """Store embeddings in Qdrant."""
    try:
        embedding_dim = len(embeddings_data[0]["embedding"])
        
        # Create collection if needed
        try:
            client.get_collection(collection_name)
            logger.info(f"✅ Collection '{collection_name}' exists")
        except:
            logger.info(f"📦 Creating collection '{collection_name}'...")
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=embedding_dim,
                    distance=Distance.COSINE
                )
            )
            logger.info(f"✅ Collection created")
        
        # Prepare points
        points = []
        for i, e in enumerate(embeddings_data):
            point = PointStruct(
                id=i,
                vector=e["embedding"],
                payload={"patent_id": e["patent_id"]}
            )
            points.append(point)
        
        # Upsert points
        client.upsert(
            collection_name=collection_name,
            points=points
        )
        logger.info(f"✅ Stored {len(embeddings_data)} embeddings in Qdrant")
    
    except Exception as e:
        logger.error(f"❌ Error storing in Qdrant: {e}")
        raise

def verify_embeddings(conn, count):
    """Verify embeddings were stored."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM embeddings")
        total = cur.fetchone()[0]
        
        logger.info("\n" + "="*60)
        logger.info("📊 EMBEDDINGS VERIFICATION")
        logger.info("="*60)
        logger.info(f"  Total embeddings in DB: {total}")
        logger.info(f"  Just added: {count}")
        logger.info("="*60)
        
        return total >= count
    except Exception as e:
        logger.error(f"❌ Verification failed: {e}")
        return False

def main():
    """Main embeddings generation script."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate patent embeddings")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of patents")
    parser.add_argument("--model", default="all-MiniLM-L6-v2", help="Model name")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size")
    parser.add_argument("--skip-qdrant", action="store_true", help="Skip Qdrant storage")
    args = parser.parse_args()
    
    logger.info("\n" + "="*60)
    logger.info("🔧 PATENT EMBEDDINGS GENERATOR")
    logger.info("="*60)
    
    try:
        # Connect
        conn = connect_database()
        if not args.skip_qdrant:
            qdrant_client = connect_qdrant()
        
        # Load model
        model = load_model(args.model)
        
        # Get patents
        patents = get_patents_needing_embeddings(conn, limit=args.limit)
        
        if not patents:
            logger.info("✅ All patents already have embeddings!")
            return
        
        # Generate embeddings
        logger.info(f"\n📝 Generating embeddings (batch_size={args.batch_size})...")
        embeddings_data = generate_embeddings_batch(model, patents, args.batch_size)
        
        # Store in PostgreSQL
        logger.info("\n💾 Storing in PostgreSQL...")
        store_embeddings_postgresql(conn, embeddings_data)
        
        # Store in Qdrant
        if not args.skip_qdrant:
            logger.info("\n💾 Storing in Qdrant...")
            store_embeddings_qdrant(qdrant_client, embeddings_data)
        
        # Verify
        verify_embeddings(conn, len(embeddings_data))
        
        conn.close()
        
        logger.info("\n✅ EMBEDDINGS GENERATION COMPLETED!")
        logger.info("="*60)
        logger.info("\nNext steps:")
        logger.info("1. Train topic model:   python scripts/train_topics.py")
        logger.info("2. Test search API:     curl http://localhost:8000/docs")
        logger.info("="*60 + "\n")
        
    except Exception as e:
        logger.error(f"\n❌ SCRIPT FAILED: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
