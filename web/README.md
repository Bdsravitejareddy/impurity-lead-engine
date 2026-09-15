# SVAK Intelligence

## Local development

```bash
cd web
npm install
VITE_DATA_MODE=local npm run dev
```

The explicit `VITE_DATA_MODE=local` flag loads sanitized data from `public/data.json` for demo/review. Production has no local fallback: set `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` at build time and authenticate through Supabase. Never expose a service-role key.

## Cloudflare Pages

- Build command: `npm run build`
- Root directory: `web`
- Output directory: `dist`
- Add `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` as encrypted environment variables.
- Do not set `VITE_DATA_MODE=local` in the production environment.
- Keep Supabase RLS enabled and use authenticated, publishable-key reads only.
