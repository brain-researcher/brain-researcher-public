# Cloudflare CDN Configuration for Brain Researcher

This directory contains all the configuration needed to set up Cloudflare CDN for the Brain Researcher platform, providing global content delivery, DDoS protection, and performance optimization.

## 🚀 Quick Start

```bash
# Run the automated setup
cd infrastructure/cloudflare
chmod +x setup.sh
./setup.sh
```

## 📁 Directory Structure

```
cloudflare/
├── terraform/              # Infrastructure as Code
│   ├── main.tf            # Main Cloudflare configuration
│   └── terraform.tfvars.example
├── workers/               # Edge computing functions
│   └── edge-optimizer.js  # Performance optimization worker
├── wrangler.toml          # Workers configuration
├── setup.sh               # Automated setup script
└── README.md              # This file
```

## 🔧 Manual Setup Steps

### 1. Get Cloudflare Credentials

1. Log in to [Cloudflare Dashboard](https://dash.cloudflare.com)
2. Go to your domain's overview page
3. Find your **Zone ID** in the API section
4. Create an API Token:
   - Go to [API Tokens](https://dash.cloudflare.com/profile/api-tokens)
   - Create Custom Token with permissions:
     - Zone:Zone:Read
     - Zone:Zone Settings:Edit
     - Zone:Page Rules:Edit
     - Zone:Cache Purge:Edit

### 2. Configure DNS Records

The Terraform configuration will create these DNS records:

| Type | Name | Content | Proxy Status |
|------|------|---------|--------------|
| A | @ | Your server IP | Proxied |
| CNAME | www | @  | Proxied |
| A | api | Your server IP | Proxied |
| A | kg | Your server IP | Proxied |
| A | agent | Your server IP | Proxied |

### 3. Apply Terraform Configuration

```bash
cd terraform

# Copy and fill in your credentials
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values

# Initialize and apply
terraform init
terraform plan
terraform apply
```

### 4. Deploy Cloudflare Workers (Optional)

Workers provide edge computing for enhanced performance:

```bash
# Install Wrangler CLI
npm install -g wrangler

# Login to Cloudflare
wrangler login

# Deploy the worker
wrangler publish --env production
```

## 🎯 Features Configured

### Performance Optimization
- ✅ HTTP/2 and HTTP/3 enabled
- ✅ Brotli compression
- ✅ Image optimization (Polish, WebP conversion)
- ✅ JavaScript/CSS minification
- ✅ Mobile optimization (Mirage)
- ✅ Always Online (serves cached content if origin is down)

### Caching Strategy
- **Static Assets** (`/_next/static/*`): 1 year
- **Images** (`/images/*`): 30 days
- **API Responses** (`/api/datasets/*`): 1 hour
- **Brain Data** (`*.nii.gz`): 1 day

### Security Features
- ✅ DDoS protection
- ✅ Web Application Firewall (WAF)
- ✅ Rate limiting (50 req/min for mutations)
- ✅ SSL/TLS encryption (Full/Strict mode)
- ✅ Security headers (CSP, HSTS, etc.)
- ✅ Bot protection

### Edge Computing
- ✅ Image format conversion (WebP/AVIF)
- ✅ API response caching
- ✅ Custom cache keys
- ✅ Cache warming

## 🔐 Origin Server Configuration

### 1. Install Cloudflare Origin Certificate

```bash
# Generate origin certificate in Cloudflare dashboard
# Save the certificate and key to:
/etc/nginx/ssl/cloudflare-origin.pem
/etc/nginx/ssl/cloudflare-origin-key.pem
```

### 2. Configure Nginx

Use the generated `nginx-origin.conf`:

```bash
sudo cp nginx-origin.conf /etc/nginx/sites-available/brain-researcher
sudo ln -s /etc/nginx/sites-available/brain-researcher /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 3. Restrict to Cloudflare IPs

```bash
# Download Cloudflare IP ranges
curl https://www.cloudflare.com/ips-v4 > /etc/nginx/cloudflare-ips.conf
curl https://www.cloudflare.com/ips-v6 >> /etc/nginx/cloudflare-ips.conf

# Format for nginx
sed -i 's/^/allow /; s/$/;/' /etc/nginx/cloudflare-ips.conf
```

## 📊 Monitoring & Analytics

### Cloudflare Dashboard
- **Analytics**: Traffic, bandwidth, threats blocked
- **Performance**: Core Web Vitals, cache hit ratio
- **Security**: Firewall events, bot scores

### Worker Analytics
```bash
# View real-time logs
wrangler tail

# View metrics
wrangler metrics
```

### Cache Performance
Monitor cache hit ratio:
- Target: >85% overall
- Static assets: >95%
- API responses: >60%

## 🛠️ Common Operations

### Purge Cache
```bash
# Purge everything
curl -X POST "https://api.cloudflare.com/client/v4/zones/YOUR_ZONE_ID/purge_cache" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"purge_everything":true}'

# Purge specific URLs
curl -X POST "https://api.cloudflare.com/client/v4/zones/YOUR_ZONE_ID/purge_cache" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"files":["https://brain-researcher.com/api/datasets"]}'
```

### Update Configuration
```bash
cd terraform
terraform plan
terraform apply
```

### Deploy Worker Updates
```bash
wrangler publish --env production
```

## 🔍 Troubleshooting

### Check if Cloudflare is Active
```bash
curl -I https://your-domain.com | grep "cf-ray"
# Should return a CF-Ray header if active
```

### Test Cache Headers
```bash
curl -I https://your-domain.com/_next/static/test.js | grep -i cache
# Should show Cache-Control headers
```

### Verify Origin IP Restriction
```bash
# From a non-Cloudflare IP
curl https://your-server-ip.com
# Should be blocked
```

## 📈 Performance Targets

After Cloudflare configuration, expect:

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Page Load Time | 3.5s | 1.4s | 60% |
| Time to First Byte | 800ms | 200ms | 75% |
| Lighthouse Score | 65 | 92 | 42% |
| Global Latency | 300ms | 50ms | 83% |
| Bandwidth Cost | $100/mo | $30/mo | 70% |

## 🔗 Useful Links

- [Cloudflare Dashboard](https://dash.cloudflare.com)
- [Cloudflare Docs](https://developers.cloudflare.com)
- [Page Rules Guide](https://support.cloudflare.com/hc/en-us/articles/218411427)
- [Workers Documentation](https://developers.cloudflare.com/workers)
- [Terraform Provider Docs](https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs)

## 📝 Next Steps

1. ✅ Complete Cloudflare setup
2. ✅ Configure origin server
3. ✅ Test performance improvements
4. ⬜ Set up Cloudflare Analytics
5. ⬜ Configure Cloudflare Stream (for video)
6. ⬜ Enable Cloudflare Pages (for static sites)
7. ⬜ Set up Cloudflare R2 (object storage)

## 💡 Tips

- Use Cloudflare's **Development Mode** when making changes
- Enable **Auto Minify** for HTML, CSS, and JS
- Use **Rocket Loader** for JavaScript optimization
- Configure **Argo Smart Routing** for better performance (paid)
- Set up **Load Balancing** for high availability (paid)

## 🆘 Support

For issues or questions:
1. Check Cloudflare System Status: https://www.cloudflarestatus.com/
2. Review logs: `wrangler tail`
3. Contact Cloudflare Support (if on paid plan)
4. Open an issue in the Brain Researcher repository