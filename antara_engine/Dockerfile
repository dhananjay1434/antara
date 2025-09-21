# Multi-stage build for production optimization
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --user -r requirements.txt

# Production stage
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Create non-root user for security
RUN groupadd -r antarauser && useradd -r -g antarauser antarauser

# Copy Python dependencies from builder stage
COPY --from=builder /root/.local /home/antarauser/.local

# Copy application code
COPY . .

# Create directory for SQLite database with proper permissions
RUN mkdir -p /app/data && chown -R antarauser:antarauser /app

# Switch to non-root user
USER antarauser

# Make sure scripts in .local are usable
ENV PATH=/home/antarauser/.local/bin:$PATH

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
