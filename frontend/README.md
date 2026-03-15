Frontend (Next.js)
==================

Environment:

Create `frontend/.env.local`:

```bash
INTERNAL_API_BASE_URL=http://127.0.0.1:3001
APP_URL=http://127.0.0.1:3000
```

Run locally:

```bash
npm ci
npm run dev
```

Then open [http://localhost:3000](http://localhost:3000).

Notes:

- `INTERNAL_API_BASE_URL` is the upstream API base used by server-rendered pages and proxy routes.
- `APP_URL` or `NEXT_PUBLIC_APP_URL` is only used to resolve same-origin fallback/proxy URLs.
- `ENABLE_QUERY_MOCK=1` enables built-in mock data for frontend-only development and CI builds that do not have a live API.
