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
    
    # Main jobs table (basic info from listing page)
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
    
    # Job details table (detailed info from job page)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER UNIQUE,
            job_url TEXT UNIQUE,
            description TEXT,
            requirements TEXT,
            job_type TEXT,
            job_level TEXT,
            education TEXT,
            category TEXT,
            salary TEXT,
            deadline TEXT,
            views INTEGER,
            scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        )
    """)
    
    # Create indexes for faster lookups
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_job_url ON jobs(job_url)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_posted_date ON jobs(posted_date)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_job_details_job_id ON job_details(job_id)
    """)
    
    conn.commit()
    conn.close()
    print("✓ Database initialized")


def job_exists(job_url: str) -> bool:
    """Check if a job URL already exists in the database."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT 1 FROM jobs WHERE job_url = ? LIMIT 1", (job_url,))
    exists = cursor.fetchone() is not None
    
    conn.close()
    return exists


def get_existing_job_urls() -> set:
    """Get all existing job URLs from the database as a set for fast lookup."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT job_url FROM jobs")
    urls = {row[0] for row in cursor.fetchall()}
    
    conn.close()
    return urls


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


def clear_all_job_details():
    """Delete all job details from the database (for re-scraping)."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM job_details")
    conn.commit()
    
    deleted = cursor.rowcount
    conn.close()
    
    print(f"✓ Deleted {deleted} job details from database")
    return deleted


# ============== Job Details Functions ==============

def insert_job_details(
    job_id: int,
    job_url: str,
    description: str = None,
    requirements: str = None,
    job_type: str = None,
    job_level: str = None,
    education: str = None,
    category: str = None,
    salary: str = None,
    deadline: str = None,
    views: int = None
) -> bool:
    """
    Insert job details into the job_details table.
    
    Args:
        job_id: ID from the jobs table
        job_url: URL of the job
        description: Job description text
        requirements: Job requirements text
        job_type: Type of employment (Full-time, Part-time, etc.)
        job_level: Seniority level
        education: Required education
        category: Job category
        salary: Salary information
        deadline: Application deadline
        views: Number of views
        
    Returns:
        True if inserted successfully, False if already exists
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO job_details 
            (job_id, job_url, description, requirements, job_type, job_level, 
             education, category, salary, deadline, views)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (job_id, job_url, description, requirements, job_type, job_level,
              education, category, salary, deadline, views))
        
        conn.commit()
        return True
        
    except sqlite3.IntegrityError:
        # Job details already exist
        return False
    finally:
        conn.close()


def get_jobs_without_details() -> list:
    """Get all jobs that don't have details scraped yet."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT j.* FROM jobs j
        LEFT JOIN job_details jd ON j.id = jd.job_id
        WHERE jd.id IS NULL
        ORDER BY j.posted_date DESC
    """)
    rows = cursor.fetchall()
    
    conn.close()
    return [dict(row) for row in rows]


def get_job_details(job_id: int) -> Optional[dict]:
    """Get details for a specific job."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM job_details WHERE job_id = ?", (job_id,))
    row = cursor.fetchone()
    
    conn.close()
    return dict(row) if row else None


def get_all_job_details() -> list:
    """Get all job details with job info."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT j.*, jd.description, jd.requirements, jd.job_type, jd.job_level,
               jd.education, jd.category, jd.salary, jd.deadline, jd.views, jd.scraped_at
        FROM jobs j
        INNER JOIN job_details jd ON j.id = jd.job_id
        ORDER BY j.posted_date DESC
    """)
    rows = cursor.fetchall()
    
    conn.close()
    return [dict(row) for row in rows]


def get_job_details_count() -> int:
    """Get count of jobs with details scraped."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM job_details")
    count = cursor.fetchone()[0]
    
    conn.close()
    return count


# Initialize database when module is imported
init_database()
