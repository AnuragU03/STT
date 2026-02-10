# Install Docker if not exists
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
fi

# Create Data Directory for Persistence
mkdir -p /home/azureuser/stt-data
chmod 777 /home/azureuser/stt-data

# Login to ACR
docker login sttpremiumacrvm8893.azurecr.io -u sttpremiumacrvm8893 -p FASnFdas5iLZCJIyxQy6H5wsSqRU4PGIOR6ZKIsx1Mu7cl9tSHrwJQQJ99CBACGhslBEqg7NAAACAZCRZpwM

# Stop/Remove Old Container
docker stop stt-app || true
docker rm stt-app || true

# Run New Container
docker run -d \
  --restart unless-stopped \
  -p 8000:8000 \
  --name stt-app \
  -v /home/azureuser/stt-data:/app/data \
  -e OPENAI_API_KEY="" \
  -e GOOGLE_API_KEY="" \
  sttpremiumacrvm8893.azurecr.io/stt-app:latest
