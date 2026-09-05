"""Services package.

Long-running, infrastructure-touching subsystems live here. Currently:
    embedding_service  — HTTP client to the GPU embedding server
    embedding_worker   — daemon loop that drains embedding_jobs

Other Flask-blueprint code stays in app/routes/.
"""
