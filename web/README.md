# SVAK Intelligence

## Local development

```bash
cd web
npm install
npm run dev
```

The demo loads sanitized local data from `public/data.json`. For production, set `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` and replace the adapter with the authenticated Supabase read adapter. Never expose a service-role key.

## Cloudflare Pages

- Build command: `npm run build`
- Root directory: `web`
- Output directory: `dist`
- Add `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` as encrypted environment variables.
- Keep Supabase RLS enabled and use authenticated, publishable-key reads only.
