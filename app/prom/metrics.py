from fastapi import APIRouter, Request, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import time

# 1. Metrics Definitions (Existing content)
REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["method", "endpoint", "status_code"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "Request latency", ["method", "endpoint"])

# 2. Router for the /metrics endpoint
router = APIRouter()

@router.get("/metrics")
def metrics():
    """Endpoint for Prometheus scraper to pull metrics."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# 3. Middleware function (To be imported and applied in main.py)
async def prometheus_middleware(request: Request, call_next):
    """
    Measures request count and latency for every endpoint.
    """
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time

    # Exclude the metrics endpoint itself from counting to prevent noise
    if request.url.path != "/metrics":
        endpoint = request.url.path
        method = request.method
        status_code = response.status_code

        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status_code=status_code).inc()
        REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(process_time)

    return response