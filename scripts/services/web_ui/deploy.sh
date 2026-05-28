#!/bin/bash

# Cloudflare Pages Deployment Script
echo "🚀 Starting Cloudflare Pages deployment..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_NAME="brain-researcher"
BUILD_OUTPUT=".next"
ACCOUNT_ID="b1f310d611aed3d5906bef441df5fd34"
ZONE_ID="874ab8d012d52c6cdd7b4bfa36742413"

echo -e "${YELLOW}Step 1: Building the application...${NC}"
npm run build

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Build failed. Please fix the errors and try again.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Build successful!${NC}"

echo -e "${YELLOW}Step 2: Deploying to Cloudflare Pages...${NC}"
echo "Project name: $PROJECT_NAME"
echo "Build output: $BUILD_OUTPUT"

# Deploy to Cloudflare Pages
wrangler pages deploy $BUILD_OUTPUT --project-name=$PROJECT_NAME

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Deployment successful!${NC}"
    echo -e "${GREEN}Your site will be available at: https://${PROJECT_NAME}.pages.dev${NC}"
else
    echo -e "${RED}❌ Deployment failed. Please check your Cloudflare configuration.${NC}"
    exit 1
fi