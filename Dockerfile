# Stage 1: Build the React Frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/client
# Copy package files
COPY client/package.json client/package-lock.json* ./
# Install dependencies
RUN npm install
# Copy source code
COPY client/ .
# Build the application
RUN npm run build

# Stage 2: Python Backend
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies (FFmpeg is required for Whisper)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy backend requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY . .

# Copy built frontend assets from Stage 1
# Vite builds to 'dist' by default, we copy it to 'static' in the python container
COPY --from=frontend-builder /app/client/dist /app/static

# Expose port 8000
EXPOSE 8000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
