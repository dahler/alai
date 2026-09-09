FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

RUN groupadd -g 2006 alaigroup && \
    useradd -u 1006 -g 2006 -m -s /bin/bash alaiuser

RUN mkdir /app && \
    chown alaiuser:alaigroup /app && \
    chmod 755 /app

WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

USER alaiuser
# Copy application code
COPY --chown=1006:2006 main.py .

# Expose port
EXPOSE 8001

# Run the application
CMD ["python", "main.py"]
