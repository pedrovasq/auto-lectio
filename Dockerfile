FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PATH="/root/.local/bin:${PATH}"

WORKDIR /app

# Install runtime dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libicu76 \
    && curl -fsSL https://d.officecli.ai/install.sh | bash \
    && officecli --version \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . .

# Create output dirs (mounted as volumes in compose)
RUN mkdir -p out build

EXPOSE 8000

# Start with gunicorn (production WSGI server)
# -t 180 increases worker timeout to accommodate larger uploads and rendering
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-t", "180", "web.app:app"]
