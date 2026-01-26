"""
Database module for storing Glorri job listings in SQLite.
"""

import sqlite3
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass


# Database configuration
DATABASE_NAME = "glorri_jobs.db"


def get_connection() -> sqlite3.Connection:
    """Get a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Initialize the database and create tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            company TEXT,
            location TEXT,
            job_url TEXT UNIQUE,
            posted_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create index for faster lookups
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_job_url ON jobs(job_url)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_posted_date ON jobs(posted_date)
    """)
    
    conn.commit()
    conn.close()
    print("✓ Database initialized")


def insert_job(title: str, company: str, location: str, job_url: str, posted_date: Optional[datetime] = None) -> bool:
    """
    Insert a single job into the database.
    
    Args:
        title: Job title
        company: Company name
        location: Job location
        job_url: URL to the job listing
        posted_date: When the job was posted
        
    Returns:
        True if inserted successfully, False if job already exists
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        posted_date_str = posted_date.strftime("%Y-%m-%d") if posted_date else None
        
        cursor.execute("""
            INSERT INTO jobs (title, company, location, job_url, posted_date)
            VALUES (?, ?, ?, ?, ?)
        """, (title, company, location, job_url, posted_date_str))
        
        conn.commit()
        return True
        
    except sqlite3.IntegrityError:
        # Job URL already exists
        return False
    finally:
        conn.close()


def insert_jobs_bulk(jobs: list) -> tuple:
    """
    Insert multiple jobs into the database.
    
    Args:
        jobs: List of JobListing objects
        
    Returns:
        Tuple of (inserted_count, skipped_count)
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    inserted = 0
    skipped = 0
    
    for job in jobs:
        try:
            posted_date_str = job.posted_date.strftime("%Y-%m-%d") if job.posted_date else None
            
            cursor.execute("""
                INSERT INTO jobs (title, company, location, job_url, posted_date)
                VALUES (?, ?, ?, ?, ?)
            """, (job.title, job.company, job.location, job.job_url, posted_date_str))
            
            inserted += 1
            
        except sqlite3.IntegrityError:
            # Job URL already exists, skip
            skipped += 1
    
    conn.commit()
    conn.close()
    
    return inserted, skipped


def get_all_jobs() -> list:
    """Get all jobs from the database."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM jobs ORDER BY posted_date DESC")
    rows = cursor.fetchall()
    
    conn.close()
    return [dict(row) for row in rows]


def get_jobs_by_date(date: datetime) -> list:
    """Get jobs posted on a specific date."""
    conn = get_connection()
    cursor = conn.cursor()
    
    date_str = date.strftime("%Y-%m-%d")
    cursor.execute("SELECT * FROM jobs WHERE posted_date = ? ORDER BY id DESC", (date_str,))
    rows = cursor.fetchall()
    
    conn.close()
    return [dict(row) for row in rows]


def get_recent_jobs(days: int = 7) -> list:
    """Get jobs posted in the last N days."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM jobs 
        WHERE posted_date >= date('now', ?)
        ORDER BY posted_date DESC
    """, (f"-{days} days",))
    rows = cursor.fetchall()
    
    conn.close()
    return [dict(row) for row in rows]


def get_job_count() -> int:
    """Get total number of jobs in database."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM jobs")
    count = cursor.fetchone()[0]
    
    conn.close()
    return count


def search_jobs(keyword: str) -> list:
    """Search jobs by keyword in title or company."""
    conn = get_connection()
    cursor = conn.cursor()
    
    search_term = f"%{keyword}%"
    cursor.execute("""
        SELECT * FROM jobs 
        WHERE title LIKE ? OR company LIKE ?
        ORDER BY posted_date DESC
    """, (search_term, search_term))
    rows = cursor.fetchall()
    
    conn.close()
    return [dict(row) for row in rows]


def clear_all_jobs():
    """Delete all jobs from the database."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM jobs")
    conn.commit()
    
    deleted = cursor.rowcount
    conn.close()
    
    print(f"✓ Deleted {deleted} jobs from database")
    return deleted


# Initialize database when module is imported
init_database()
