#!/bin/bash

# Cloudflare Pages SSR Deployment Script
# Uses @cloudflare/next-on-pages for full SSR support

set -e  # Exit on error

echo "🚀 Starting Cloudflare Pages SSR deployment..."
echo "======================================="

# Step 1: Clean previous builds
echo "📦 Cleaning previous builds..."
rm -rf .next .vercel out

# Step 2: Install dependencies
echo "📦 Installing dependencies..."
npm ci --legacy-peer-deps

# Step 3: Build Next.js app
echo "🔨 Building Next.js application..."
npm run build

# Step 4: Run next-on-pages to generate Cloudflare Pages Functions
echo "☁️ Generating Cloudflare Pages Functions..."
npx @cloudflare/next-on-pages

# Step 5: Deploy to Cloudflare Pages
echo "🚢 Deploying to Cloudflare Pages..."
echo "   Static files: .vercel/output/static"
echo "   Functions: .vercel/output/functions"

npx wrangler pages deploy .vercel/output/static \
  --functions .vercel/output/functions \
  --project-name=brain-researcher \
  --compatibility-date=2024-01-01

echo "======================================="
echo "✅ Deployment complete!"
echo ""
echo "📝 Next steps:"
echo "1. Go to Cloudflare Dashboard → Pages → brain-researcher"
echo "2. Click 'Custom domains' to add your domain"
echo "3. Follow the instructions to configure DNS"
echo ""
echo "🌐 Your site will be available at:"
echo "   https://brain-researcher.pages.dev (temporary URL)"
echo "   https://your-domain.com (after domain setup)"