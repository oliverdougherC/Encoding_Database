cd ~/Encoding_Database
git pull --rebase --autostash

# Rebuild only the server image
docker compose -f docker-compose.prod.yml build server

# Restart just the server container (no downtime for others)
docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate server

# Apply Prisma migrations
docker compose -f docker-compose.prod.yml exec server npx prisma migrate deploy

# Verify
curl -i http://localhost/health/ready
docker compose -f docker-compose.prod.yml logs --tail=80 server