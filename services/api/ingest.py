"""
Patent + Innovation Radar: PatentsView API Ingestion Client
Handles incremental ingestion from PatentsView API with rate limiting, retries, and validation.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import requests
import backoff
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
import json

logger = logging.getLogger(__name__)


class PatentsViewClient:
    """
    Client for fetching patents from PatentsView API.
    Ref: https://www.patentsview.org/download/data-download-tables
    """
    
    BASE_URL = "https://api.patentsview.org/patents/query"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        rate_limit_per_sec: float = 1.0,
        retries: int = 3,
        timeout: int = 30
    ):
        self.api_key = api_key
        self.rate_limit_per_sec = rate_limit_per_sec
        self.retries = retries
        self.timeout = timeout
        self.last_request_time = 0
    
    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self.last_request_time
        wait_time = (1.0 / self.rate_limit_per_sec) - elapsed
        if wait_time > 0:
            time.sleep(wait_time)
        self.last_request_time = time.time()
    
    @backoff.on_exception(
        backoff.expo,
        (requests.exceptions.RequestException, requests.exceptions.Timeout),
        max_tries=3,
        factor=2
    )
    def fetch_patents(
        self,
        since: Optional[datetime] = None,
        limit: int = 5000,
        offset: int = 0
    ) -> Dict:
        """
        Fetch patents from PatentsView API.
        
        Args:
            since: Only fetch patents published after this date
            limit: Batch size (max 5000)
            offset: Pagination offset
        
        Returns:
            API response dict
        """
        self._rate_limit()
        
        # Build query
        query = {
            "q": "{\"patent_date\":{\"gte\":\"" + (since or datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d") + "\"}}",
            "o": {
                "page": offset // limit + 1,
                "per_page": limit,
                "sort": [{"patent_date": "desc"}]
            },
            "f": [
                "patent_id",
                "patent_title",
                "patent_abstract",
                "patent_num_claims",
                "patent_date",
                "filing_date",
                "assignee_id",
                "assignee_name",
                "assignee_type",
                "inventor_id",
                "inventor_name",
                "cpc_code",
                "cited_patent_id",
                "publication_number"
            ]
        }
        
        params = {
            "q": query["q"],
            "o": json.dumps(query["o"]),
            "f": json.dumps(query["f"])
        }
        
        if self.api_key:
            params["key"] = self.api_key
        
        logger.info(f"Fetching patents: {params}")
        response = requests.get(
            self.BASE_URL,
            params=params,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()


class PatentDataLoader:
    """
    Loads patent data into PostgreSQL.
    Handles upserts, transaction management, and validation.
    """
    
    def __init__(self, db_url: str, echo: bool = False):
        self.engine = create_engine(
            db_url,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            echo=echo
        )
    
    def load_patents(self, patents_data: List[Dict]) -> Dict:
        """
        Load patent records into database.
        Expects records from PatentsView API response.
        """
        stats = {
            "inserted": 0,
            "updated": 0,
            "errors": 0,
            "error_list": []
        }
        
        with self.engine.begin() as conn:
            for patent in patents_data:
                try:
                    # Normalize data
                    patent_id = patent.get("patent_id")
                    if not patent_id:
                        logger.warning(f"Skipping patent with no ID: {patent}")
                        continue
                    
                    publication_date = patent.get("patent_date")
                    filing_date = patent.get("filing_date")
                    
                    # Upsert patent record
                    stmt = text("""
                        INSERT INTO patents (
                            patent_id, publication_number, publication_date, filing_date,
                            title, abstract, num_claims,
                            primary_cpc_code, cpc_codes,
                            num_citations, raw_data,
                            ingested_at
                        ) VALUES (
                            :patent_id, :pub_num, :pub_date, :file_date,
                            :title, :abstract, :num_claims,
                            :cpc, :cpcs,
                            :citations, :raw,
                            NOW()
                        )
                        ON CONFLICT (patent_id) DO UPDATE SET
                            last_updated_at = NOW(),
                            raw_data = EXCLUDED.raw_data,
                            abstract = COALESCE(EXCLUDED.abstract, patents.abstract),
                            num_claims = COALESCE(EXCLUDED.num_claims, patents.num_claims)
                    """)
                    
                    # Extract CPC codes
                    cpc_codes = []
                    if isinstance(patent.get("cpc_code"), list):
                        cpc_codes = [str(c) for c in patent["cpc_code"]]
                    elif patent.get("cpc_code"):
                        cpc_codes = [str(patent["cpc_code"])]
                    
                    primary_cpc = cpc_codes[0] if cpc_codes else None
                    
                    conn.execute(stmt, {
                        "patent_id": patent_id,
                        "pub_num": patent.get("publication_number") or f"US{patent_id}",
                        "pub_date": publication_date,
                        "file_date": filing_date,
                        "title": patent.get("patent_title"),
                        "abstract": patent.get("patent_abstract"),
                        "num_claims": patent.get("patent_num_claims"),
                        "cpc": primary_cpc,
                        "cpcs": cpc_codes,
                        "citations": len(patent.get("cited_patent_id", [])) if isinstance(patent.get("cited_patent_id"), list) else 0,
                        "raw": json.dumps(patent)
                    })
                    
                    # Load assignees
                    assignees = patent.get("assignees", [])
                    if not isinstance(assignees, list):
                        assignees = [assignees] if assignees else []
                    
                    for idx, assignee in enumerate(assignees):
                        if not assignee or not assignee.get("assignee_id"):
                            continue
                        
                        assignee_id = assignee.get("assignee_id")
                        stmt_assignee = text("""
                            INSERT INTO assignees (
                                assignee_id, name, type, raw_data, ingested_at
                            ) VALUES (
                                :id, :name, :type, :raw, NOW()
                            )
                            ON CONFLICT (assignee_id) DO UPDATE SET
                                last_updated_at = NOW()
                        """)
                        
                        conn.execute(stmt_assignee, {
                            "id": assignee_id,
                            "name": assignee.get("assignee_name"),
                            "type": assignee.get("assignee_type"),
                            "raw": json.dumps(assignee)
                        })
                        
                        # Link patent to assignee
                        stmt_link = text("""
                            INSERT INTO patent_assignees (patent_id, assignee_id, position)
                            VALUES (:patent_id, :assignee_id, :pos)
                            ON CONFLICT DO NOTHING
                        """)
                        conn.execute(stmt_link, {
                            "patent_id": patent_id,
                            "assignee_id": assignee_id,
                            "pos": idx
                        })
                    
                    # Load inventors
                    inventors = patent.get("inventors", [])
                    if not isinstance(inventors, list):
                        inventors = [inventors] if inventors else []
                    
                    for idx, inventor in enumerate(inventors):
                        if not inventor or not inventor.get("inventor_id"):
                            continue
                        
                        inventor_id = inventor.get("inventor_id")
                        stmt_inventor = text("""
                            INSERT INTO inventors (
                                inventor_id, name, raw_data, ingested_at
                            ) VALUES (
                                :id, :name, :raw, NOW()
                            )
                            ON CONFLICT (inventor_id) DO UPDATE SET
                                last_updated_at = NOW()
                        """)
                        
                        conn.execute(stmt_inventor, {
                            "id": inventor_id,
                            "name": inventor.get("inventor_name"),
                            "raw": json.dumps(inventor)
                        })
                        
                        # Link patent to inventor
                        stmt_inv_link = text("""
                            INSERT INTO patent_inventors (patent_id, inventor_id, position)
                            VALUES (:patent_id, :inventor_id, :pos)
                            ON CONFLICT DO NOTHING
                        """)
                        conn.execute(stmt_inv_link, {
                            "patent_id": patent_id,
                            "inventor_id": inventor_id,
                            "pos": idx
                        })
                    
                    stats["inserted"] += 1
                    
                except Exception as e:
                    logger.error(f"Error loading patent {patent.get('patent_id')}: {e}")
                    stats["errors"] += 1
                    stats["error_list"].append(str(e))
        
        return stats
    
    def get_last_ingestion_date(self) -> Optional[datetime]:
        """Get the most recent patent publication date in the database."""
        with self.engine.connect() as conn:
            result = conn.execute(
                text("SELECT MAX(publication_date) FROM patents")
            )
            row = result.fetchone()
            return row[0] if row and row[0] else None


def ingest_patents(
    db_url: str,
    api_key: Optional[str] = None,
    since_days: int = 7
) -> Dict:
    """
    Main ingestion function.
    Fetches patents from PatentsView API and loads into database.
    """
    logger.info("Starting patent ingestion...")
    
    client = PatentsViewClient(api_key=api_key)
    loader = PatentDataLoader(db_url)
    
    # Determine since date
    since = datetime.now() - timedelta(days=since_days)
    logger.info(f"Fetching patents since: {since.date()}")
    
    all_stats = {
        "total_inserted": 0,
        "total_updated": 0,
        "total_errors": 0,
        "batches_processed": 0
    }
    
    # Paginate through results
    offset = 0
    batch_size = 1000
    max_batches = 10  # Limit for safety
    
    while offset < (max_batches * batch_size):
        logger.info(f"Fetching batch at offset {offset}...")
        
        response = client.fetch_patents(since=since, limit=batch_size, offset=offset)
        
        if "patents" not in response or not response["patents"]:
            logger.info("No more patents to fetch")
            break
        
        patents = response["patents"]
        logger.info(f"Fetched {len(patents)} patents")
        
        # Load into database
        stats = loader.load_patents(patents)
        all_stats["total_inserted"] += stats["inserted"]
        all_stats["total_updated"] += stats["updated"]
        all_stats["total_errors"] += stats["errors"]
        all_stats["batches_processed"] += 1
        
        logger.info(f"Batch stats: {stats}")
        
        # Check pagination
        if len(patents) < batch_size:
            logger.info("Reached end of results")
            break
        
        offset += batch_size
    
    logger.info(f"Ingestion complete: {all_stats}")
    return all_stats


if __name__ == "__main__":
    import os
    
    # Example usage
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/patent_radar")
    api_key = os.getenv("PATENTSVIEW_API_KEY")
    
    result = ingest_patents(db_url, api_key=api_key, since_days=7)
    print(f"Result: {result}")
