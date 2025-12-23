"""
Patent + Innovation Radar: ML Models
Embeddings service, BERTopic modeling, trend acceleration detection, novelty scoring.
"""

import logging
import os
import json
from typing import List, Tuple, Dict, Optional
from datetime import datetime, timedelta
import numpy as np
from dataclasses import dataclass

import torch
from sentence_transformers import SentenceTransformer
from bertopic import BERTopic
from sklearn.preprocessing import normalize
import lightgbm as lgb
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import qdrant_client
from qdrant_client.models import PointStruct, Distance, VectorParams

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration & Constants
# ============================================================================

@dataclass
class ModelConfig:
    """Model configuration."""
    embedding_model_id: str = "sentence-transformers/all-mpnet-base-v2"
    embedding_dim: int = 768
    batch_size: int = 32
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    
    # BERTopic config
    n_topics: int = 50
    min_topic_size: int = 50
    
    # Novelty model
    novelty_model_path: str = "/models/novelty_lgb.pkl"


config = ModelConfig()


# ============================================================================
# Embeddings Service
# ============================================================================

class EmbeddingService:
    """
    Manages patent embeddings using Sentence-Transformers.
    Stores vectors in Qdrant for semantic search.
    """
    
    def __init__(
        self,
        model_id: str = config.embedding_model_id,
        db_url: str = os.getenv("DATABASE_URL"),
        qdrant_url: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    ):
        self.model_id = model_id
        self.model = SentenceTransformer(model_id)
        self.embedding_dim = self.model.get_sentence_embedding_dimension()
        
        # Database
        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
        
        # Qdrant
        self.qdrant = qdrant_client.QdrantClient(url=qdrant_url)
        self._init_qdrant()
    
    def _init_qdrant(self):
        """Initialize Qdrant collection."""
        try:
            self.qdrant.get_collection("patents")
        except:
            self.qdrant.create_collection(
                collection_name="patents",
                vectors_config=VectorParams(
                    size=self.embedding_dim,
                    distance=Distance.COSINE
                )
            )
            logger.info("Created Qdrant collection 'patents'")
    
    def embed_patents(self, patent_ids: List[str], batch_size: int = 32) -> Dict[str, np.ndarray]:
        """
        Embed patents (texts: title + abstract).
        Returns: {patent_id: embedding_vector}
        """
        db = self.SessionLocal()
        try:
            # Fetch patent texts
            query = text("""
            SELECT patent_id, title, abstract
            FROM patents
            WHERE patent_id = ANY(:ids)
            """)
            
            results = db.execute(query, {"ids": patent_ids}).fetchall()
            
            embeddings = {}
            for patent_id, title, abstract in results:
                text = f"{title} {abstract or ''}".strip()
                embedding = self.model.encode([text], batch_size=1)[0]
                embeddings[patent_id] = embedding
            
            return embeddings
        
        finally:
            db.close()
    
    def store_embeddings(self, embeddings: Dict[str, np.ndarray]):
        """Store embeddings in Qdrant."""
        points = []
        db = self.SessionLocal()
        
        try:
            for idx, (patent_id, embedding) in enumerate(embeddings.items()):
                point = PointStruct(
                    id=idx,
                    vector=embedding.tolist(),
                    payload={"patent_id": patent_id}
                )
                points.append(point)
                
                # Update database
                db.execute(text("""
                INSERT INTO embeddings (patent_id, embedding_model_id, embedding_dim, qdrant_id, created_at)
                VALUES (:patent_id, :model_id, :dim, :qdrant_id, NOW())
                ON CONFLICT (patent_id) DO UPDATE SET
                    updated_at = NOW()
                """), {
                    "patent_id": patent_id,
                    "model_id": self.model_id,
                    "dim": self.embedding_dim,
                    "qdrant_id": str(idx)
                })
            
            db.commit()
            
            # Store in Qdrant
            self.qdrant.upsert(collection_name="patents", points=points)
            logger.info(f"Stored {len(points)} embeddings in Qdrant")
        
        finally:
            db.close()
    
    def search_similar(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.6
    ) -> List[Tuple[str, float]]:
        """
        Semantic search for similar patents.
        Returns: [(patent_id, similarity_score), ...]
        """
        # Embed query
        query_embedding = self.model.encode([query])[0]
        
        # Search Qdrant
        results = self.qdrant.search(
            collection_name="patents",
            query_vector=query_embedding.tolist(),
            limit=limit,
            score_threshold=threshold
        )
        
        return [(hit.payload["patent_id"], hit.score) for hit in results]


# ============================================================================
# Topic Modeling Service
# ============================================================================

class TopicModelingService:
    """
    BERTopic-based topic modeling for patents.
    """
    
    def __init__(
        self,
        db_url: str = os.getenv("DATABASE_URL"),
        n_topics: int = config.n_topics,
        min_topic_size: int = config.min_topic_size
    ):
        self.db_url = db_url
        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.n_topics = n_topics
        self.min_topic_size = min_topic_size
        self.model = None
    
    def prepare_documents(self) -> Tuple[List[str], List[str]]:
        """Fetch documents (abstracts) from database."""
        db = self.SessionLocal()
        try:
            # Fetch recent + random historical
            query = text("""
            SELECT patent_id, abstract
            FROM patents
            WHERE abstract IS NOT NULL AND abstract != ''
            ORDER BY RANDOM()
            LIMIT 100000
            """)
            
            results = db.execute(query).fetchall()
            
            patent_ids = [r[0] for r in results]
            documents = [r[1] for r in results]
            
            logger.info(f"Prepared {len(documents)} documents for topic modeling")
            return documents, patent_ids
        
        finally:
            db.close()
    
    def fit_model(self) -> BERTopic:
        """
        Fit BERTopic model on patent abstracts.
        """
        documents, patent_ids = self.prepare_documents()
        
        logger.info(f"Fitting BERTopic with {len(documents)} documents...")
        
        # Fit BERTopic
        self.model = BERTopic(
            language="english",
            nr_topics=self.n_topics,
            min_topic_size=self.min_topic_size,
            embedding_model=config.embedding_model_id,
            calculate_probabilities=True,
            verbose=True
        )
        
        topics, probs = self.model.fit_transform(documents)
        
        logger.info(f"Fitted model: {len(self.model.get_topics())} topics")
        
        return self.model, topics, probs, patent_ids
    
    def update_topic_assignments(self, topics: np.ndarray, probs: np.ndarray, patent_ids: List[str]):
        """Store topic assignments in database."""
        db = self.SessionLocal()
        try:
            model_version = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # First, insert topics
            for topic_id, topic_info in self.model.get_topics().items():
                if topic_id == -1:  # Skip outlier topic
                    continue
                
                keywords = [w[0] for w in topic_info[:10]]
                
                db.execute(text("""
                INSERT INTO topics (topic_id, name, top_keywords, coherence_score, model_version, created_at, updated_at)
                VALUES (:topic_id, :name, :keywords, :coherence, :model_version, NOW(), NOW())
                ON CONFLICT (topic_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    top_keywords = EXCLUDED.top_keywords,
                    updated_at = NOW()
                """), {
                    "topic_id": topic_id,
                    "name": f"Topic {topic_id}",
                    "keywords": keywords,
                    "coherence": 0.5,  # Placeholder
                    "model_version": model_version
                })
            
            # Then, assign topics to patents
            for patent_id, topic_id, topic_probs in zip(patent_ids, topics, probs):
                if topic_id == -1:
                    continue
                
                prob = float(topic_probs[topic_id]) if topic_id < len(topic_probs) else 0.0
                
                db.execute(text("""
                INSERT INTO topic_assignments (patent_id, topic_id, probability)
                VALUES (:patent_id, :topic_id, :prob)
                ON CONFLICT (patent_id, topic_id) DO UPDATE SET
                    probability = EXCLUDED.probability
                """), {
                    "patent_id": patent_id,
                    "topic_id": int(topic_id),
                    "prob": prob
                })
            
            db.commit()
            logger.info(f"Updated topic assignments for {len(patent_ids)} patents")
        
        finally:
            db.close()


# ============================================================================
# Trend Acceleration Detection
# ============================================================================

class TrendAccelerationDetector:
    """
    Detect trends with accelerating filing rates.
    Uses z-score of weekly filing counts.
    """
    
    def __init__(self, db_url: str = os.getenv("DATABASE_URL")):
        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
    
    def compute_trend_acceleration(self, period_weeks: int = 52) -> Dict[str, float]:
        """
        Compute z-score of weekly filing rates for topics and CPC codes.
        Returns: {topic_or_cpc_id: z_score}
        """
        db = self.SessionLocal()
        try:
            # Compute weekly counts for each topic
            query = text("""
            SELECT 
                DATE_TRUNC('week', p.publication_date)::date as week,
                ta.topic_id,
                COUNT(*) as count
            FROM patents p
            JOIN topic_assignments ta ON p.patent_id = ta.patent_id
            WHERE p.publication_date >= NOW() - INTERVAL ':weeks weeks'
            GROUP BY DATE_TRUNC('week', p.publication_date), ta.topic_id
            ORDER BY week, topic_id
            """)
            
            results = db.execute(query, {"weeks": period_weeks}).fetchall()
            
            z_scores = {}
            
            # Group by topic_id
            topic_weeks = {}
            for week, topic_id, count in results:
                if topic_id not in topic_weeks:
                    topic_weeks[topic_id] = []
                topic_weeks[topic_id].append(count)
            
            # Compute z-scores
            for topic_id, counts in topic_weeks.items():
                counts = np.array(counts)
                mean = counts.mean()
                std = counts.std()
                
                if std > 0 and len(counts) > 0:
                    # Z-score of most recent week
                    z_score = (counts[-1] - mean) / std
                    z_scores[f"topic_{topic_id}"] = float(z_score)
            
            return z_scores
        
        finally:
            db.close()


# ============================================================================
# Novelty Scoring Model
# ============================================================================

class NoveltyScorer:
    """
    Score patents for novelty based on:
    - Embedding distance to nearest neighbors
    - New CPC co-occurrences
    - Citation patterns
    """
    
    def __init__(
        self,
        db_url: str = os.getenv("DATABASE_URL"),
        qdrant_url: str = os.getenv("QDRANT_URL"),
        model_path: str = config.novelty_model_path
    ):
        self.db_url = db_url
        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.qdrant = qdrant_client.QdrantClient(url=qdrant_url)
        self.model_path = model_path
        self.model = self._load_model()
    
    def _load_model(self):
        """Load LightGBM novelty ranking model (if exists)."""
        if os.path.exists(self.model_path):
            return lgb.Booster(model_file=self.model_path)
        return None
    
    def compute_features(self, patent_id: str) -> Dict[str, float]:
        """
        Compute novelty features for a patent.
        Returns: {feature_name: value}
        """
        db = self.SessionLocal()
        try:
            # 1. Embedding distance to nearest 50 neighbors
            embedding_result = db.execute(
                text("SELECT qdrant_id FROM embeddings WHERE patent_id = :id"),
                {"id": patent_id}
            ).fetchone()
            
            if not embedding_result:
                return {}
            
            qdrant_id = embedding_result[0]
            
            # Search for nearest neighbors (approximate)
            # In production, use actual similarity search
            nearest_distance = 0.5  # Placeholder
            
            # 2. Patent filing date
            filing_result = db.execute(
                text("SELECT filing_date FROM patents WHERE patent_id = :id"),
                {"id": patent_id}
            ).fetchone()
            
            days_since_filing = 0
            if filing_result:
                days_since_filing = (datetime.now().date() - filing_result[0]).days
            
            # 3. Citation count
            cite_result = db.execute(
                text("SELECT num_citations FROM patents WHERE patent_id = :id"),
                {"id": patent_id}
            ).fetchone()
            
            num_citations = cite_result[0] if cite_result else 0
            
            # 4. CPC co-occurrence novelty
            cpc_result = db.execute(
                text("SELECT cpc_codes FROM patents WHERE patent_id = :id"),
                {"id": patent_id}
            ).fetchone()
            
            num_cpcs = len(cpc_result[0]) if cpc_result and cpc_result[0] else 1
            
            features = {
                "embedding_distance": float(nearest_distance),
                "days_since_filing": days_since_filing,
                "num_citations": int(num_citations),
                "num_cpcs": num_cpcs,
                "is_recent": 1 if days_since_filing < 30 else 0
            }
            
            return features
        
        finally:
            db.close()
    
    def score_patents(self, patent_ids: List[str]) -> Dict[str, float]:
        """
        Score a batch of patents for novelty.
        Returns: {patent_id: novelty_score (0-100)}
        """
        scores = {}
        
        for patent_id in patent_ids:
            features = self.compute_features(patent_id)
            
            if not features:
                scores[patent_id] = 50.0  # Default middle score
                continue
            
            # Simple scoring (can be replaced with LGB model prediction)
            # Higher embedding distance + recent + multi-CPC = higher novelty
            embedding_score = features["embedding_distance"] * 30
            recency_score = features["is_recent"] * 20
            cpc_score = min(features["num_cpcs"] * 10, 30)
            
            score = embedding_score + recency_score + cpc_score
            score = min(max(score, 0), 100)  # Clamp to 0-100
            
            scores[patent_id] = float(score)
        
        return scores


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Example: embed patents
    print("Initializing embedding service...")
    embed_service = EmbeddingService()
    
    print("Done!")
