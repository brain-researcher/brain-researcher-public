# Cloudflare Pages Deployment Guide

## Prerequisites
- Cloudflare account
- GitHub account with your private repo
- Your domain added to Cloudflare

## Step 1: Prepare for Deployment

### Option A: Standard Next.js Build (Recommended)
Your app will be deployed with server-side rendering support using Cloudflare's @cloudflare/next-on-pages.

1. No changes needed to next.config.js

### Option B: Static Export (If you don't need SSR)
1. Update `next.config.js`:
```javascript
module.exports = {
  reactStrictMode: true,
  output: 'export',
};
```

2. Run `npm run build` to test the build locally

## Step 2: Connect to Cloudflare Pages

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. Navigate to **Workers & Pages** → **Pages**
3. Click **Connect to Git**
4. Authorize Cloudflare to access your GitHub account
5. Select your private repository: `brain_researcher`
6. Choose the branch to deploy (usually `main` or `master`)

## Step 3: Configure Build Settings

### For Standard Build:
```
Framework preset: Next.js
Build command: npm run build
Build output directory: .next
Root directory: apps/web-ui
```

### For Static Export:
```
Framework preset: Next.js (Static HTML Export)
Build command: npm run build
Build output directory: out
Root directory: apps/web-ui
```

## Step 4: Environment Variables

Add these in Cloudflare Pages settings:

```bash
# Required
NODE_VERSION=18

# Keep browser traffic same-origin through the Web UI
NEXT_PUBLIC_USE_API_PROXY=true

# Server-side downstream targets for Next.js route handlers
BR_AGENT_URL=https://agent.your-api.com
BR_ORCHESTRATOR_URL=https://orchestrator.your-api.com
BR_NEUROKG_URL=https://kg.your-api.com

# Only set this if your websocket endpoint is not available at same-origin /ws
# NEXT_PUBLIC_WS_URL=wss://orchestrator.your-api.com/ws

# Optional direct public service overrides (advanced / opt-out only)
# NEXT_PUBLIC_AGENT_API=https://agent.your-api.com
# NEXT_PUBLIC_ORCHESTRATOR_URL=https://orchestrator.your-api.com
# NEXT_PUBLIC_NEUROKG_API=https://kg.your-api.com

# Supabase (if using)
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_key

# Analytics (optional)
NEXT_PUBLIC_POSTHOG_KEY=your_key
NEXT_PUBLIC_POSTHOG_HOST=https://app.posthog.com

# Backend CORS (set in orchestrator environment)
ORCHESTRATOR_ALLOWED_ORIGINS=https://your-site.pages.dev,https://your-custom-domain
```

## Step 5: Deploy

1. Click **Save and Deploy**
2. Wait for the build to complete (usually 2-5 minutes)
3. Your site will be available at: `your-project.pages.dev`

## Step 6: Custom Domain

1. Go to your Pages project → **Custom domains**
2. Click **Set up a custom domain**
3. Enter your domain (e.g., `app.yourdomain.com`)
4. Cloudflare will automatically:
   - Add the necessary DNS records
   - Enable SSL/TLS
   - Set up CDN

## Build Configuration File

The `.cloudflare/deployment-config.json` file has been created with:
```json
{
  "name": "brain-researcher",
  "compatibility_date": "2024-01-01",
  "build": {
    "command": "npm run build",
    "directory": ".next",
    "watch_paths": [
      "src/**",
      "public/**",
      "package.json",
      "next.config.js"
    ]
  },
  "env": {
    "NODE_VERSION": "18"
  }
}
```

## Troubleshooting

### If build fails:
1. Check Node version compatibility (use Node 18)
2. Ensure all dependencies are in package.json
3. Check for hardcoded localhost URLs

### For Dynamic Features:
- API Routes → Will work with Cloudflare Workers
- Image Optimization → Use Cloudflare Images or disable Next.js image optimization
- ISR/SSG → Supported with @cloudflare/next-on-pages
- Same-origin proxy mode is preferred; only disable it if you intentionally want
  the browser to call downstream services directly

## Alternative: Deploy with Wrangler CLI

If you prefer command line deployment:

```bash
# Install Wrangler
npm install -g wrangler

# Login to Cloudflare
wrangler login

# Deploy
wrangler pages deploy .next --project-name=brain-researcher
```

## Notes
- Free plan includes: 500 builds/month, unlimited requests, unlimited bandwidth
- Each push to your repo triggers automatic deployment
- Pull requests get preview URLs
