# Build stage
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies + refresh packaging toolchain to patched versions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Install Python dependencies
# requirements.txt includes `-e .` (editable install), so project metadata and
# package source must be present at install time.
COPY requirements.txt pyproject.toml README.md ./
COPY app ./app
COPY destinations ./destinations
RUN pip install --no-cache-dir --user -r requirements.txt

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Refresh packaging toolchain in final image to avoid known CVEs reported by Trivy
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy installed packages from builder
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH

# Copy application code
COPY --chown=appuser:appuser . .

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Expose port
EXPOSE 8000

# Run with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
