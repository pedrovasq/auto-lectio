FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
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
