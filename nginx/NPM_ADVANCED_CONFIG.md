Nginx Proxy Manager (NPM) Hardening Guide

Use these snippets in NPM → Proxy Hosts → Edit Host → Advanced → Custom Nginx Configuration. Apply to both your frontend host and API host (or a single combined host if you route by path).

1) Enforce HTTPS and HSTS

```
# Force HTTPS at the edge
if ($scheme = http) {
  return 301 https://$host$request_uri;
}

# Long‑lived HSTS (tweak max-age as needed)
add_header Strict-Transport-Security "max-age=15552000; includeSubDomains" always;
```

2) Security Headers

```
add_header Referrer-Policy "no-referrer" always;
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;

# Content Security Policy – adjust if you introduce external CDNs
add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'" always;
```

3) Limit Methods and Body Size (API paths)

If you terminate both frontend and API at the same host, scope this to your API location, e.g. `location ~ ^/(submit|query|health.*)$ { ... }`. In NPM, you can add a custom location block under Advanced Configuration.

```
client_max_body_size 1m;
limit_except GET POST { deny all; }
proxy_read_timeout 60s;
proxy_send_timeout 60s;
```

4) Upstream Headers

```
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

5) CORS at the application layer

Set `CORS_ORIGIN` in the server `.env` to a comma‑separated allowlist (e.g. `https://yourdomain.com,https://www.yourdomain.com`). In production, wildcard `*` is rejected by the server.

6) TLS

- Use valid certificates (Let’s Encrypt in NPM). Replace any self‑signed placeholders in deployment.
- Enable only TLSv1.2+ in NPM SSL settings.

7) Do not expose app containers directly

- In `docker-compose.prod.yml`, the `server` and `frontend` services are not published on host ports; only NPM (`nginx-proxy-manager`) should bind to 80/443 on the host.

8) Rate limiting (optional at NPM)

You can also enable NPM-level throttling. The backend already rate-limits globally and on `/submit`.


