import time
import requests
import os
from prometheus_client import Gauge, start_http_server

# --- Configuration ---
# Target to scrape (The FastAPI Web service, accessible by its service name)
TARGET_URL = os.environ.get("TARGET_METRICS_URL", "http://fastapi-web:8080/metrics")
SCRAPE_INTERVAL = int(os.environ.get("SCRAPE_INTERVAL_SECONDS", 15))
EXPORTER_PORT = int(os.environ.get("EXPORTER_PORT", 9100)) # Port the scraper will expose

# --- Prometheus Metrics Setup ---
# The scraper container will expose metrics about the target service's health and latency.
FASTAPI_UP = Gauge(
    'fastapi_service_up', 
    'Shows if the FastAPI web service metrics endpoint is reachable (1) or not (0)'
)
SCRAPE_LATENCY = Gauge(
    'fastapi_scrape_latency_seconds', 
    'Latency of scraping the FastAPI web service metrics endpoint'
)

def scrape_fastapi_status():
    """
    Fetches the metrics endpoint and updates the local Gauges.
    This logic turns the scraper from a client/logger into a dedicated exporter.
    """
    start_time = time.time()
    
    try:
        # Use the requests library to hit the target URL
        response = requests.get(TARGET_URL, timeout=5)
        response.raise_for_status() 
        
        # Success: The service is reachable and returned a 2xx status code
        latency = time.time() - start_time
        FASTAPI_UP.set(1)
        SCRAPE_LATENCY.set(latency)
        
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] OK: Latency={latency:.3f}s")
        
        # NOTE: If you wanted to process and re-expose *specific* metrics
        # from response.text, that complex parsing logic would go here.
        # For now, we focus on status/latency.

    except requests.exceptions.ConnectionError:
        # Failure: Could not connect to the service
        FASTAPI_UP.set(0)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] FAILED: Connection Error. Target unreachable.")
    except requests.exceptions.HTTPError as e:
        # Failure: Received a 4xx or 5xx status code
        FASTAPI_UP.set(0)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] FAILED: HTTP Error: {e.response.status_code}")
    except Exception as e:
        # General failure
        FASTAPI_UP.set(0)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] FAILED: Unexpected error: {e}")


if __name__ == "__main__":
    # 1. Start the HTTP server for Prometheus to scrape
    start_http_server(EXPORTER_PORT)
    print(f"Metrics exporter started on port {EXPORTER_PORT}. Prometheus can now scrape this service.")
    
    print(f"Starting metric collection loop. Target: {TARGET_URL}, Interval: {SCRAPE_INTERVAL}s")
    
    # 2. Start the infinite loop to collect and update metrics
    while True:
        scrape_fastapi_status()
        time.sleep(SCRAPE_INTERVAL)