Deploying the frontend

Vercel (recommended)
1) Import the `frontend` directory as a project.
2) Set Environment Variables:
   - `NEXT_PUBLIC_API_BASE_URL` = `https://encodingdb.platinumlabs.dev`
3) Build & Output Settings: default (Next.js 15 app dir).
4) Deploy.

Netlify
1) Create a new site from Git.
2) Base directory: `frontend`
3) Build command: `npm run build`
4) Publish directory: `.next`
5) Environment variables:
   - `NEXT_PUBLIC_API_BASE_URL` = `https://encodingdb.platinumlabs.dev`
6) Deploy, then enable Next.js runtime (if prompted).

Local
```
cd frontend
npm install
echo "NEXT_PUBLIC_API_BASE_URL=http://localhost:3001" > .env.local
npm run dev
```

