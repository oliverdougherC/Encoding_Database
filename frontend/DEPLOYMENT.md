Deploying the frontend

Vercel (recommended)
1) Import the `frontend` directory as a project.
2) Set Environment Variables:
   - `INTERNAL_API_BASE_URL` = `https://encodingdb.platinumlabs.dev`
   - `APP_URL` = your deployed frontend URL
3) Build & Output Settings: default (Next.js 15 app dir).
4) Deploy.

Netlify
1) Create a new site from Git.
2) Base directory: `frontend`
3) Build command: `npm run build`
4) Publish directory: `.next`
5) Environment variables:
   - `INTERNAL_API_BASE_URL` = `https://encodingdb.platinumlabs.dev`
   - `APP_URL` = your deployed frontend URL
6) Deploy, then enable Next.js runtime (if prompted).

Local
```
cd frontend
npm install
cat > .env.local <<'EOF'
INTERNAL_API_BASE_URL=http://localhost:3001
APP_URL=http://127.0.0.1:3000
EOF
npm run dev
```

Optional:

- Set `ENABLE_QUERY_MOCK=1` when you want the frontend to build or run without a live API.
