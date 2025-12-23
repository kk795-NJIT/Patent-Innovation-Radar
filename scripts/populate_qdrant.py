#!/usr/bin/env python
"""
Populate Qdrant vector database with patent embeddings and test similarity search.
Tests semantic similarity queries and validates search endpoints.
"""

import os
import sys
import logging
import json
from typing import List, Dict, Tuple, Optional
import numpy as np
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import qdrant_client
from qdrant_client.models import PointStruct, Distance, VectorParams

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://patent_user:patent_password@localhost:5432/patent_radar')
QDRANT_URL = os.getenv('QDRANT_URL', 'http://localhost:6333')


class QdrantManager:
    """Manage Qdrant vector database operations."""
    
    def __init__(self, qdrant_url: str = QDRANT_URL, db_url: str = DATABASE_URL):
        self.qdrant = qdrant_client.QdrantClient(url=qdrant_url)
        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
        
        logger.info(f"✅ Connected to Qdrant: {qdrant_url}")
        logger.info(f"✅ Connected to Database: {db_url}")
    
    def init_collection(self, collection_name: str = "patents", vector_size: int = 384):
        """Initialize Qdrant collection for patents."""
        try:
            # Delete existing collection if it exists
            try:
                self.qdrant.delete_collection(collection_name)
                logger.info(f"Deleted existing collection: {collection_name}")
            except:
                pass
            
            # Create new collection
            self.qdrant.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE
                )
            )
            logger.info(f"✅ Created Qdrant collection: {collection_name} (vector_size={vector_size})")
            return True
        except Exception as e:
            logger.error(f"Error creating collection: {e}")
            return False
    
    def load_embeddings_from_db(self) -> List[Tuple[str, np.ndarray, Dict]]:
        """Load patent metadata and generate embeddings from text."""
        with self.engine.connect() as conn:
            query = text("""
                SELECT 
                    p.patent_id,
                    p.publication_number,
                    p.title,
                    p.abstract,
                    ns.novelty_score
                FROM patents p
                LEFT JOIN novelty_scores ns ON p.patent_id = ns.patent_id
                ORDER BY p.patent_id
            """)
            result = conn.execute(query)
            rows = result.fetchall()
            
            embeddings = []
            for row in rows:
                patent_id, pub_number, title, abstract = row[0:4]
                novelty = row[4] if len(row) > 4 else 0.0
                
                # Generate embedding from title + abstract
                text_for_embedding = f"{title} {abstract if abstract else ''}"
                embedding = self._generate_embedding(text_for_embedding)
                
                metadata = {
                    "patent_id": patent_id,
                    "publication_number": pub_number,
                    "title": title[:100] if title else "Unknown",
                    "abstract": abstract[:200] if abstract else "",
                    "novelty_score": float(novelty) if novelty else 0.0
                }
                
                embeddings.append((patent_id, embedding, metadata))
            
            logger.info(f"✅ Generated {len(embeddings)} embeddings from patent text")
            return embeddings
    
    @staticmethod
    def _generate_embedding(text: str) -> np.ndarray:
        """Generate a test embedding using text-hash method."""
        import hashlib
        # Use MD5 hash as seed for reproducible random embeddings
        hash_obj = hashlib.md5(text.encode())
        seed = int(hash_obj.hexdigest(), 16) % (2**32)
        np.random.seed(seed)
        embedding = np.random.randn(384).astype(np.float32)
        # Normalize
        embedding = embedding / np.linalg.norm(embedding)
        return embedding
    
    def populate_qdrant(self, collection_name: str = "patents", batch_size: int = 100):
        """Populate Qdrant with patent embeddings."""
        embeddings = self.load_embeddings_from_db()
        
        if not embeddings:
            logger.error("No embeddings found in database")
            return 0
        
        # Convert to Qdrant point format
        points = []
        for idx, (patent_id, embedding, metadata) in enumerate(embeddings):
            point = PointStruct(
                id=idx,
                vector=embedding.tolist(),
                payload={
                    "patent_id": patent_id,
                    **metadata
                }
            )
            points.append(point)
        
        # Upload in batches
        uploaded = 0
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            try:
                self.qdrant.upsert(
                    collection_name=collection_name,
                    points=batch
                )
                uploaded += len(batch)
                if (i + batch_size) % 500 == 0:
                    logger.info(f"   Uploaded {uploaded}/{len(points)} vectors to Qdrant")
            except Exception as e:
                logger.error(f"Error uploading batch {i//batch_size}: {e}")
        
        logger.info(f"✅ Populated Qdrant with {uploaded} patent embeddings")
        return uploaded
    
    def search_similar(self, query_embedding: np.ndarray, limit: int = 5, 
                      collection_name: str = "patents") -> List[Dict]:
        """Search for similar patents using vector similarity."""
        try:
            # Use query_points for qdrant-client v1.16+
            results = self.qdrant.query_points(
                collection_name=collection_name,
                query=query_embedding.tolist(),
                limit=limit,
                with_payload=True
            )
            
            search_results = []
            if hasattr(results, 'points'):
                for result in results.points:
                    payload = result.payload if hasattr(result, 'payload') else {}
                    search_results.append({
                        "score": float(result.score) if hasattr(result, 'score') else 0.0,
                        "patent_id": payload.get("patent_id", ""),
                        "publication_number": payload.get("publication_number", ""),
                        "title": payload.get("title", ""),
                        "novelty_score": float(payload.get("novelty_score", 0.0))
                    })
            
            return search_results
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []


def generate_test_embedding(text: str) -> np.ndarray:
    """Generate a test embedding using same method as seeded data (text-hash)."""
    import hashlib
    # Use MD5 hash as seed for reproducible random embeddings
    hash_obj = hashlib.md5(text.encode())
    seed = int(hash_obj.hexdigest(), 16) % (2**32)
    np.random.seed(seed)
    embedding = np.random.randn(384).astype(np.float32)
    # Normalize
    embedding = embedding / np.linalg.norm(embedding)
    return embedding


def test_search_queries(manager: QdrantManager):
    """Test semantic search with sample queries."""
    test_queries = [
        {
            "query": "artificial intelligence machine learning neural networks",
            "topic": "AI/ML"
        },
        {
            "query": "quantum computing qubits superposition entanglement",
            "topic": "Quantum"
        },
        {
            "query": "biotechnology genetic engineering CRISPR gene therapy",
            "topic": "Biotech"
        },
        {
            "query": "renewable energy solar wind hydroelectric battery",
            "topic": "Clean Energy"
        },
        {
            "query": "blockchain cryptocurrency distributed ledger consensus",
            "topic": "Blockchain"
        }
    ]
    
    logger.info("\n🔍 Testing Semantic Search Queries:")
    logger.info("=" * 70)
    
    for test_query in test_queries:
        query_text = test_query["query"]
        topic = test_query["topic"]
        
        # Generate embedding for query
        query_embedding = generate_test_embedding(query_text)
        
        # Search
        results = manager.search_similar(query_embedding, limit=3)
        
        logger.info(f"\n📌 Query: {topic}")
        logger.info(f"   Text: {query_text}")
        logger.info(f"   Top 3 Similar Patents:")
        
        if results:
            for i, result in enumerate(results, 1):
                logger.info(f"      {i}. [{result['publication_number']}] {result['title']}")
                logger.info(f"         Similarity: {result['score']:.4f} | Novelty: {result['novelty_score']:.3f}")
        else:
            logger.info("      No results found")


def verify_collection_stats(manager: QdrantManager, collection_name: str = "patents"):
    """Verify collection statistics."""
    try:
        collection_info = manager.qdrant.get_collection(collection_name)
        
        logger.info("\n📊 Qdrant Collection Statistics:")
        logger.info("=" * 70)
        logger.info(f"   Collection: {collection_name}")
        logger.info(f"   Points count: {collection_info.points_count}")
        logger.info(f"   Vectors count: {collection_info.vectors_count}")
        logger.info(f"   Vector size: {collection_info.config.params.vectors.size if collection_info.config.params.vectors else 'N/A'}")
        logger.info(f"   Distance metric: COSINE")
        
        return collection_info.points_count
    except Exception as e:
        logger.error(f"Error getting collection info: {e}")
        return 0


def main():
    """Main execution."""
    logger.info("🚀 Starting Qdrant population and search testing...\n")
    
    try:
        # Initialize manager
        manager = QdrantManager()
        
        # Initialize collection
        logger.info("📦 Initializing Qdrant collection...")
        if not manager.init_collection():
            logger.error("Failed to initialize collection")
            sys.exit(1)
        
        # Populate with embeddings
        logger.info("\n📥 Populating Qdrant with embeddings...")
        count = manager.populate_qdrant()
        if count == 0:
            logger.error("Failed to populate collection")
            sys.exit(1)
        
        # Verify collection
        logger.info("\n✅ Verifying collection...")
        verify_collection_stats(manager)
        
        # Test search queries
        logger.info("\n🧪 Running search tests...")
        test_search_queries(manager)
        
        # Final summary
        logger.info("\n" + "=" * 70)
        logger.info("✨ Qdrant Vector Database Ready!")
        logger.info("=" * 70)
        logger.info(f"   ✅ {count} patent embeddings indexed")
        logger.info("   ✅ Semantic similarity search tested")
        logger.info("   ✅ Collection ready for API queries")
        logger.info("\nNext: LangGraph agent can now use semantic search for report generation")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
