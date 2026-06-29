# Database module
from .db import (
    init_database,
    get_connection,
    insert_job,
    insert_jobs_bulk,
    get_all_jobs,
    get_job_count,
    get_unsent_jobs,
    mark_jobs_as_sent,
    get_unsent_jobs_count,
    get_jobs_without_details,
    insert_job_details,
    get_job_details_count,
    reset_sent_jobs_without_details,
)

__all__ = [
    'init_database',
    'get_connection',
    'insert_job',
    'insert_jobs_bulk',
    'get_all_jobs',
    'get_job_count',
    'get_unsent_jobs',
    'mark_jobs_as_sent',
    'get_unsent_jobs_count',
    'get_jobs_without_details',
    'insert_job_details',
    'get_job_details_count',
    'reset_sent_jobs_without_details',
]
