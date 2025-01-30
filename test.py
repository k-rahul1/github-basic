import logging
import os
import sys
import json
import time
import threading
import requests
from flask import request
from datetime import datetime
from logging.handlers import RotatingFileHandler

# Splunk Configuration (Update This)
SPLUNK_HEC_URL: str = "https://your-splunk-server:8088"
SPLUNK_TOKEN: str = "YOUR_SPLUNK_TOKEN"
SPLUNK_INDEX: str = "your_index"
SPLUNK_SOURCE: str = "api_logs"

class JSONFormatter(logging.Formatter):
    """Formats logs as structured JSON for Splunk ingestion."""
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "thread": record.threadName,  # Capturing thread name
            "endpoint": getattr(record, "endpoint", "N/A"),
            "status": getattr(record, "status", "N/A"),
            "runtime": getattr(record, "runtime", "N/A"),
            "message": record.getMessage(),
        }
        return json.dumps(log_record)

def get_log_directory() -> str:
    """Returns the directory path for logs based on the current date."""
    date_s: str = datetime.now().strftime("%Y-%m-%d")
    log_dir: str = os.path.join("logs", date_s)
    os.makedirs(log_dir, exist_ok=True)  # Create if not exists
    return log_dir

def setup_logger() -> logging.Logger:
    """Configures the centralized API logger with console, file, and Splunk integration."""
    log_dir: str = get_log_directory()
    logger: logging.Logger = logging.getLogger("api_logger")
    logger.setLevel(logging.DEBUG)

    if logger.hasHandlers():
        return logger  # Avoid duplicate handlers

    # File Handler with Rotation
    log_file: str = os.path.join(log_dir, "api.log")
    file_handler: RotatingFileHandler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3)
    file_handler.setLevel(logging.DEBUG)

    # Console Handler
    console_handler: logging.StreamHandler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    # Apply JSON Formatter
    json_formatter: JSONFormatter = JSONFormatter()
    file_handler.setFormatter(json_formatter)
    console_handler.setFormatter(json_formatter)

    # Add Handlers to Logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

logger: logging.Logger = setup_logger()

def send_to_splunk(log_data: dict) -> None:
    """Sends logs to Splunk via HTTP Event Collector (HEC)."""
    headers: dict = {
        "Authorization": f"Splunk {SPLUNK_TOKEN}",
        "Content-Type": "application/json"
    }
    event: dict = {
        "event": log_data,
        "index": SPLUNK_INDEX,
        "source": SPLUNK_SOURCE
    }
    try:
        response: requests.Response = requests.post(f"{SPLUNK_HEC_URL}/services/collector", headers=headers, json=event, timeout=2)
        if response.status_code not in [200, 201, 202]:
            print(f"Failed to send log to Splunk: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Splunk log error: {str(e)}")

def get_endpoint_logger(endpoint: str) -> logging.Logger:
    """Creates a logger specific to an API endpoint."""
    log_dir: str = get_log_directory()
    endpoint_file: str = os.path.join(log_dir, f"{endpoint}.log")
    
    endpoint_logger: logging.Logger = logging.getLogger(f"api_{endpoint}")
    endpoint_logger.setLevel(logging.DEBUG)

    if not endpoint_logger.hasHandlers():
        file_handler: RotatingFileHandler = RotatingFileHandler(endpoint_file, maxBytes=2*1024*1024, backupCount=2)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(JSONFormatter())
        endpoint_logger.addHandler(file_handler)

    return endpoint_logger

def log_api_request(func):
    """Decorator to log API execution time and send logs to Splunk."""
    def wrapper(*args, **kwargs):
        start_time: float = time.time()
        response = func(*args, **kwargs)
        end_time: float = time.time()

        runtime: float = round(end_time - start_time, 3)
        endpoint: str = request.path.strip("/").replace("/", "_")
        thread_name: str = threading.current_thread().name  # Capturing thread name
        status: int = response.status_code

        log_data: dict = {
            "timestamp": datetime.now().isoformat(),
            "level": "INFO",
            "thread": thread_name,
            "endpoint": request.path,
            "status": status,
            "runtime": runtime,
            "message": "API request processed"
        }

        # Log centrally and to specific endpoint log file
        logger.info("", extra=log_data)
        endpoint_logger: logging.Logger = get_endpoint_logger(endpoint)
        endpoint_logger.info("", extra=log_data)

        # Send logs to Splunk
        send_to_splunk(log_data)

        return response
    return wrapper
