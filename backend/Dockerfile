FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

RUN groupadd -g 2006 alaigroup && \
    useradd -u 1006 -g 2006 -m -s /bin/bash alaiuser

RUN mkdir /app && \
    chown alaiuser:alaigroup /app && \
    chmod 755 /app

WORKDIR /app

# # Install system dependencies
# RUN apt-get update && apt-get install -y \
#     gcc \
#     libpq-dev \
#     && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

USER alaiuser
# Copy application code
COPY --chown=1006:2006 app/ ./app/
COPY --chown=1006:2006 alembic/ ./alembic
COPY --chown=1006:2006 alembic.ini ./

# Expose port
EXPOSE 8000

# Run the application
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
