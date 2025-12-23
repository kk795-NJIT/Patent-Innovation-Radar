#!/usr/bin/env python3
"""
Seed sample patent data into PostgreSQL for local testing.
Generates 1K-5K synthetic patents without hitting PatentsView API limits.
"""

import os
import sys
import random
import json
from datetime import datetime, timedelta
from faker import Faker
import psycopg2
from psycopg2.extras import execute_values
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fake = Faker()

# Patent data templates
TECHNOLOGY_DOMAINS = [
    "Artificial Intelligence", "Machine Learning", "Deep Learning", "Natural Language Processing",
    "Computer Vision", "Robotics", "Autonomous Systems", "IoT", "Blockchain",
    "Quantum Computing", "Edge Computing", "Cloud Computing", "Data Analytics",
    "Cybersecurity", "Bioinformatics", "Medical Devices", "Drug Discovery",
    "Materials Science", "Renewable Energy", "Battery Technology"
]

CPC_CLASSES = [
    "G06F", "G06N", "H04L", "H04N", "H04W",
    "G01N", "A61B", "A61K", "C07C", "F24J"
]

ASSIGNEE_TYPES = ["Corporation", "Individual", "University", "Government", "Research Institute"]

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
        logger.info("✅ Connected to PostgreSQL database")
        return conn
    except Exception as e:
        logger.error(f"❌ Failed to connect to database: {e}")
        raise

def generate_patents(count=1000):
    """Generate synthetic patent records."""
    patents = []
    for i in range(count):
        filing_date = datetime.now() - timedelta(days=random.randint(1, 3650))
        publication_date = filing_date + timedelta(days=random.randint(180, 365))
        
        patent = {
            "patent_id": f"US{10000000 + i}",
            "publication_number": f"US{10000000 + i}B1",
            "title": fake.sentence(nb_words=8).rstrip("."),
            "abstract": fake.paragraph(nb_sentences=6),
            "claims": fake.paragraph(nb_sentences=15),
            "filing_date": filing_date.date(),
            "publication_date": publication_date.date(),
            "num_claims": random.randint(5, 50),
            "num_citations": random.randint(0, 100),
            "primary_cpc_code": random.choice(CPC_CLASSES),
            "patent_type": "utility"
        }
        patents.append(patent)
    
    logger.info(f"✅ Generated {len(patents)} synthetic patents")
    return patents

def generate_assignees(count=100):
    """Generate synthetic assignee records."""
    assignees = []
    for i in range(count):
        assignee = {
            "assignee_id": f"ASS{1000 + i}",
            "name": fake.company(),
            "country": random.choice(["US", "JP", "DE", "CN", "GB", "KR", "FR"]),
            "type": random.choice(ASSIGNEE_TYPES)
        }
        assignees.append(assignee)
    
    logger.info(f"✅ Generated {len(assignees)} synthetic assignees")
    return assignees

def generate_inventors(count=500):
    """Generate synthetic inventor records."""
    inventors = []
    for i in range(count):
        inventor = {
            "inventor_id": f"INV{1000 + i}",
            "name": fake.name(),
        }
        inventors.append(inventor)
    
    logger.info(f"✅ Generated {len(inventors)} synthetic inventors")
    return inventors

def insert_assignees(conn, assignees):
    """Insert assignees into database."""
    try:
        cur = conn.cursor()
        query = """
            INSERT INTO assignees (assignee_id, name, country, type)
            VALUES %s
            ON CONFLICT (assignee_id) DO NOTHING
        """
        values = [(a["assignee_id"], a["name"], a["country"], a["type"]) for a in assignees]
        execute_values(cur, query, values, page_size=100)
        conn.commit()
        logger.info(f"✅ Inserted {len(assignees)} assignees")
    except Exception as e:
        logger.error(f"❌ Error inserting assignees: {e}")
        conn.rollback()
        raise

def insert_inventors(conn, inventors):
    """Insert inventors into database."""
    try:
        cur = conn.cursor()
        query = """
            INSERT INTO inventors (inventor_id, name)
            VALUES %s
            ON CONFLICT (inventor_id) DO NOTHING
        """
        values = [(i["inventor_id"], i["name"]) for i in inventors]
        execute_values(cur, query, values, page_size=100)
        conn.commit()
        logger.info(f"✅ Inserted {len(inventors)} inventors")
    except Exception as e:
        logger.error(f"❌ Error inserting inventors: {e}")
        conn.rollback()
        raise

def insert_patents(conn, patents):
    """Insert patents into database."""
    try:
        cur = conn.cursor()
        query = """
            INSERT INTO patents 
            (patent_id, publication_number, title, abstract, claims, filing_date, publication_date, 
             num_claims, num_citations, primary_cpc_code, patent_type)
            VALUES %s
            ON CONFLICT (patent_id) DO NOTHING
        """
        values = [
            (p["patent_id"], p["publication_number"], p["title"], p["abstract"], p["claims"],
             p["filing_date"], p["publication_date"], p["num_claims"],
             p["num_citations"], p["primary_cpc_code"], p["patent_type"])
            for p in patents
        ]
        execute_values(cur, query, values, page_size=100)
        conn.commit()
        logger.info(f"✅ Inserted {len(patents)} patents")
    except Exception as e:
        logger.error(f"❌ Error inserting patents: {e}")
        conn.rollback()
        raise

def insert_patent_assignees(conn, patents, assignees, max_per_patent=3):
    """Link patents to assignees."""
    try:
        cur = conn.cursor()
        values = []
        
        for patent in patents:
            num_assignees = random.randint(1, max_per_patent)
            selected_assignees = random.sample(assignees, min(num_assignees, len(assignees)))
            
            for idx, assignee in enumerate(selected_assignees):
                values.append((patent["patent_id"], assignee["assignee_id"], idx + 1))
        
        query = """
            INSERT INTO patent_assignees (patent_id, assignee_id, position)
            VALUES %s
            ON CONFLICT (patent_id, assignee_id) DO NOTHING
        """
        execute_values(cur, query, values, page_size=100)
        conn.commit()
        logger.info(f"✅ Created {len(values)} patent-assignee links")
    except Exception as e:
        logger.error(f"❌ Error inserting patent-assignees: {e}")
        conn.rollback()
        raise

def insert_patent_inventors(conn, patents, inventors, max_per_patent=5):
    """Link patents to inventors."""
    try:
        cur = conn.cursor()
        values = []
        
        for patent in patents:
            num_inventors = random.randint(1, max_per_patent)
            selected_inventors = random.sample(inventors, min(num_inventors, len(inventors)))
            
            for idx, inventor in enumerate(selected_inventors):
                values.append((patent["patent_id"], inventor["inventor_id"], idx + 1))
        
        query = """
            INSERT INTO patent_inventors (patent_id, inventor_id, position)
            VALUES %s
            ON CONFLICT (patent_id, inventor_id) DO NOTHING
        """
        execute_values(cur, query, values, page_size=100)
        conn.commit()
        logger.info(f"✅ Created {len(values)} patent-inventor links")
    except Exception as e:
        logger.error(f"❌ Error inserting patent-inventors: {e}")
        conn.rollback()
        raise

def insert_citations(conn, patents):
    """Insert patent citations."""
    try:
        cur = conn.cursor()
        values = []
        
        for patent in patents:
            # Each patent cites 0-20 other patents
            num_citations = random.randint(0, 20)
            for _ in range(num_citations):
                cited_patent = random.choice(patents)
                if cited_patent["patent_id"] != patent["patent_id"]:
                    values.append((patent["patent_id"], cited_patent["patent_id"]))
        
        # Remove duplicates
        values = list(set(values))
        
        query = """
            INSERT INTO citations (citing_patent_id, cited_patent_id)
            VALUES %s
            ON CONFLICT (citing_patent_id, cited_patent_id) DO NOTHING
        """
        execute_values(cur, query, values, page_size=100)
        conn.commit()
        logger.info(f"✅ Created {len(values)} patent citations")
    except Exception as e:
        logger.error(f"❌ Error inserting citations: {e}")
        conn.rollback()
        raise

def verify_data(conn):
    """Verify inserted data."""
    try:
        cur = conn.cursor()
        
        counts = {}
        tables = ["patents", "assignees", "inventors", "patent_assignees", 
                 "patent_inventors", "citations"]
        
        for table in tables:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            counts[table] = count
        
        logger.info("\n" + "="*60)
        logger.info("📊 DATA VERIFICATION SUMMARY")
        logger.info("="*60)
        for table, count in counts.items():
            logger.info(f"  {table:.<30} {count:>10} records")
        logger.info("="*60)
        
        return counts
    except Exception as e:
        logger.error(f"❌ Error verifying data: {e}")
        raise

def main():
    """Main seed data script."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Seed sample patent data")
    parser.add_argument("--patents", type=int, default=1000, help="Number of patents to generate")
    parser.add_argument("--assignees", type=int, default=100, help="Number of assignees to generate")
    parser.add_argument("--inventors", type=int, default=500, help="Number of inventors to generate")
    args = parser.parse_args()
    
    logger.info("\n" + "="*60)
    logger.info("🌱 PATENT RADAR - SEED DATA SCRIPT")
    logger.info("="*60)
    
    try:
        # Connect to database
        conn = connect_database()
        
        # Generate data
        logger.info("\n📝 Generating synthetic data...")
        assignees = generate_assignees(args.assignees)
        inventors = generate_inventors(args.inventors)
        patents = generate_patents(args.patents)
        
        # Insert data
        logger.info("\n💾 Inserting data into database...")
        insert_assignees(conn, assignees)
        insert_inventors(conn, inventors)
        insert_patents(conn, patents)
        insert_patent_assignees(conn, patents, assignees)
        insert_patent_inventors(conn, patents, inventors)
        insert_citations(conn, patents)
        
        # Verify
        logger.info("\n🔍 Verifying inserted data...")
        verify_data(conn)
        
        conn.close()
        
        logger.info("\n✅ SEED DATA SCRIPT COMPLETED SUCCESSFULLY!")
        logger.info("="*60)
        logger.info("\nNext steps:")
        logger.info("1. Generate embeddings: python scripts/generate_embeddings.py")
        logger.info("2. Train topic model:   python scripts/train_topics.py")
        logger.info("3. Test API endpoints:  curl http://localhost:8000/docs")
        logger.info("="*60 + "\n")
        
    except Exception as e:
        logger.error(f"\n❌ SCRIPT FAILED: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
