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

# Install system dependencies (FFmpeg for Whisper, ODBC for SQL Server)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    gnupg \
    ca-certificates \
    apt-transport-https \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/11/prod bullseye main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && apt-get install -y unixodbc-dev \
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
