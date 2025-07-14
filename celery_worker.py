from celery import Celery
import os
from dotenv import load_dotenv

load_dotenv()

celery_app = Celery(
    "tasks",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0")
)

@celery_app.task
def process_document_task(file_path, metadata):
    # Import your existing functions and call them here
    from app.routes.upload import full_process_document
    return full_process_document(file_path, metadata)
