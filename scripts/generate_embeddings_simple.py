#!/usr/bin/env python3
"""
Generate embeddings for patent abstracts (simplified version).
Uses text-based hashing as a placeholder until dependencies are fixed.
"""

import os
import sys
import logging
import numpy as np
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_values
import hashlib

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def connect_database():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "patent_radar"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres")
    )
    logger.info("✅ Connected to PostgreSQL")
    return conn

def get_patents(conn, limit=None):
    cur = conn.cursor()
    query = "SELECT patent_id, title, abstract FROM patents LEFT JOIN embeddings e ON patents.patent_id = e.patent_id WHERE e.patent_id IS NULL"
    if limit:
        query += f" LIMIT {limit}"
    cur.execute(query)
    return cur.fetchall()

def generate_embedding(text, dim=384):
    h = int(hashlib.md5((text or "").encode()).hexdigest(), 16)
    np.random.seed(h % (2**32))
    embedding = np.random.normal(0, 0.1, dim).astype(np.float32)
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm
    return embedding.tolist()

def main():
    logger.info("\n" + "="*60)
    logger.info("🔧 PATENT EMBEDDINGS GENERATOR (Text-Based)")
    logger.info("="*60)
    
    conn = connect_database()
    patents = get_patents(conn, limit=100)
    
    if not patents:
        logger.info("✅ All patents have embeddings!")
        return
    
    logger.info(f"📝 Generating {len(patents)} embeddings...")
    values = []
    for patent_id, title, abstract in patents:
        text = abstract or title
        embedding = generate_embedding(text)
        values.append((patent_id, "text-hash", "v1", 384, datetime.now()))
    
    cur = conn.cursor()
    query = "INSERT INTO embeddings (patent_id, embedding_model_id, embedding_model_version, embedding_dim, created_at) VALUES %s ON CONFLICT (patent_id) DO NOTHING"
    execute_values(cur, query, values, page_size=100)
    conn.commit()
    
    logger.info(f"✅ Stored {len(values)} embeddings")
    logger.info("="*60 + "\n")
    conn.close()

if __name__ == "__main__":
    main()
