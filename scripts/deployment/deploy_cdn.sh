#!/bin/bash

# Brain Researcher CDN Deployment Script
# Automates the deployment of CDN infrastructure and optimizations

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
CDN_DIR="$PROJECT_ROOT/src/brain_researcher/infrastructure/cdn"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
ENVIRONMENT="${ENVIRONMENT:-production}"
AWS_REGION="${AWS_REGION:-us-east-1}"
DEPLOY_CLOUDFRONT="${DEPLOY_CLOUDFRONT:-true}"
DEPLOY_NGINX="${DEPLOY_NGINX:-true}"
WARM_CACHE="${WARM_CACHE:-true}"
START_MONITORING="${START_MONITORING:-true}"

# Logging
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1"
    exit 1
}

info() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')] INFO:${NC} $1"
}

# Check dependencies
check_dependencies() {
    log "Checking dependencies..."

    local deps=("terraform" "aws" "nginx" "node" "npm" "docker")
    local missing_deps=()

    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &> /dev/null; then
            missing_deps+=("$dep")
        fi
    done

    if [ ${#missing_deps[@]} -ne 0 ]; then
        error "Missing dependencies: ${missing_deps[*]}. Please install them first."
    fi

    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        error "AWS credentials not configured. Please run 'aws configure' first."
    fi

    log "Dependencies check passed ✓"
}

# Create necessary directories
setup_directories() {
    log "Setting up directories..."

    local dirs=(
        "$CDN_DIR/cache"
        "$CDN_DIR/logs"
        "$CDN_DIR/reports/performance"
        "$CDN_DIR/nginx/certs"
        "$CDN_DIR/terraform/.terraform"
    )

    for dir in "${dirs[@]}"; do
        mkdir -p "$dir"
    done

    log "Directories setup complete ✓"
}

# Generate SSL certificates (self-signed for development)
generate_ssl_certs() {
    log "Generating SSL certificates..."

    local cert_dir="$CDN_DIR/nginx/certs"

    if [ "$ENVIRONMENT" = "development" ]; then
        # Generate self-signed certificate for development
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout "$cert_dir/brain-researcher-key.pem" \
            -out "$cert_dir/brain-researcher.pem" \
            -subj "/C=US/ST=State/L=City/O=BrainResearcher/CN=localhost"

        log "Self-signed SSL certificate generated ✓"
    else
        warn "For production, use proper SSL certificates from Let's Encrypt or AWS ACM"
    fi
}

# Build optimized Next.js application
build_nextjs_app() {
    log "Building optimized Next.js application..."

    local web_ui_dir="$PROJECT_ROOT/apps/web-ui"

    if [ ! -d "$web_ui_dir" ]; then
        error "Web UI directory not found: $web_ui_dir"
    fi

    cd "$web_ui_dir"

    # Install dependencies
    npm ci --production=false

    # Keep CDN builds on the canonical web-ui Next.js config. The alternate
    # optimized config is intentionally not copied here because it has drifted
    # from the live same-origin routing contract.
    log "Using canonical apps/web-ui/next.config.js for CDN build ✓"

    # Build with optimizations
    NODE_ENV=production npm run build

    # Copy service worker
    if [ -f "$CDN_DIR/service-worker/sw.js" ]; then
        cp "$CDN_DIR/service-worker/sw.js" public/
        cp "$CDN_DIR/service-worker/sw-register.js" public/
        log "Service worker files copied ✓"
    fi

    cd "$SCRIPT_DIR"
    log "Next.js build complete ✓"
}

# Optimize images
optimize_images() {
    log "Optimizing images..."

    local web_ui_dir="$PROJECT_ROOT/apps/web-ui"
    local image_dirs=("$web_ui_dir/public" "$web_ui_dir/src/assets")

    for dir in "${image_dirs[@]}"; do
        if [ -d "$dir" ]; then
            info "Optimizing images in $dir"
            node "$CDN_DIR/optimization/image-optimizer.js" optimize-dir "$dir" "$web_ui_dir/public/optimized"
        fi
    done

    log "Image optimization complete ✓"
}

# Deploy Terraform infrastructure
deploy_terraform() {
    if [ "$DEPLOY_CLOUDFRONT" != "true" ]; then
        info "Skipping CloudFront deployment (DEPLOY_CLOUDFRONT=false)"
        return 0
    fi

    log "Deploying CloudFront infrastructure with Terraform..."

    local tf_dir="$CDN_DIR/terraform"
    cd "$tf_dir"

    # Initialize Terraform
    terraform init

    # Create terraform.tfvars if it doesn't exist
    if [ ! -f "terraform.tfvars" ]; then
        cat > terraform.tfvars <<EOF
aws_region = "$AWS_REGION"
environment = "$ENVIRONMENT"
static_bucket_name = "brain-researcher-static-$ENVIRONMENT-$(date +%s)"
app_domain_name = "${APP_DOMAIN:-app.brain-researcher.com}"
api_domain_name = "${API_DOMAIN:-api.brain-researcher.com}"
domain_aliases = ${DOMAIN_ALIASES:-["brain-researcher.com", "www.brain-researcher.com"]}
cloudfront_price_class = "${CLOUDFRONT_PRICE_CLASS:-PriceClass_100}"
EOF
        log "Created terraform.tfvars with default values"
    fi

    # Plan deployment
    terraform plan -out=tfplan

    # Apply if auto-approved or user confirms
    if [ "${AUTO_APPROVE:-false}" = "true" ]; then
        terraform apply -auto-approve tfplan
    else
        echo -n "Deploy CloudFront infrastructure? (y/N): "
        read -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            terraform apply tfplan
        else
            warn "CloudFront deployment skipped by user"
            return 0
        fi
    fi

    # Save outputs
    terraform output -json > "$CDN_DIR/terraform-outputs.json"

    cd "$SCRIPT_DIR"
    log "CloudFront deployment complete ✓"
}

# Configure and deploy Nginx
deploy_nginx() {
    if [ "$DEPLOY_NGINX" != "true" ]; then
        info "Skipping Nginx deployment (DEPLOY_NGINX=false)"
        return 0
    fi

    log "Configuring and deploying Nginx..."

    local nginx_dir="$CDN_DIR/nginx"

    # Test Nginx configuration
    nginx -t -c "$nginx_dir/nginx.conf" || error "Nginx configuration test failed"

    if command -v docker &> /dev/null; then
        # Deploy with Docker
        info "Deploying Nginx with Docker..."

        # Build Nginx image
        cat > "$nginx_dir/Dockerfile" <<EOF
FROM nginx:alpine

# Install additional modules
RUN apk add --no-cache nginx-mod-http-brotli

# Copy configuration
COPY nginx.conf /etc/nginx/nginx.conf
COPY certs/ /etc/nginx/certs/

# Copy static files if they exist
COPY static/ /var/www/html/ 2>/dev/null || true

# Create cache directories
RUN mkdir -p /var/cache/nginx/api /var/cache/nginx/static /var/cache/nginx/pages

# Set permissions
RUN chown -R nginx:nginx /var/cache/nginx /var/www/html

EXPOSE 80 443 8080

CMD ["nginx", "-g", "daemon off;"]
EOF

        # Build and run container
        docker build -t brain-researcher-nginx "$nginx_dir"

        # Stop existing container if running
        docker stop brain-researcher-nginx 2>/dev/null || true
        docker rm brain-researcher-nginx 2>/dev/null || true

        # Run new container
        docker run -d \
            --name brain-researcher-nginx \
            --network brain-researcher-network \
            -p 80:80 -p 443:443 -p 8080:8080 \
            -v "$nginx_dir/logs:/var/log/nginx" \
            brain-researcher-nginx

        log "Nginx deployed with Docker ✓"
    else
        # Deploy directly (requires sudo)
        info "Deploying Nginx directly..."

        sudo cp "$nginx_dir/nginx.conf" /etc/nginx/nginx.conf
        sudo nginx -t
        sudo systemctl reload nginx

        log "Nginx deployed directly ✓"
    fi
}

# Upload static assets to S3
upload_static_assets() {
    log "Uploading static assets to S3..."

    # Get S3 bucket name from Terraform outputs
    local tf_outputs="$CDN_DIR/terraform-outputs.json"

    if [ ! -f "$tf_outputs" ]; then
        warn "Terraform outputs not found, skipping S3 upload"
        return 0
    fi

    local bucket_name
    bucket_name=$(jq -r '.s3_bucket_name.value' "$tf_outputs")

    if [ "$bucket_name" = "null" ] || [ -z "$bucket_name" ]; then
        warn "S3 bucket name not found in Terraform outputs"
        return 0
    fi

    # Upload Next.js build artifacts
    local web_ui_dir="$PROJECT_ROOT/apps/web-ui"

    if [ -d "$web_ui_dir/.next/static" ]; then
        aws s3 sync "$web_ui_dir/.next/static" "s3://$bucket_name/_next/static/" \
            --delete --cache-control "public, max-age=31536000, immutable"
    fi

    if [ -d "$web_ui_dir/public" ]; then
        aws s3 sync "$web_ui_dir/public" "s3://$bucket_name/" \
            --exclude "*.html" --cache-control "public, max-age=86400"
    fi

    log "Static assets uploaded to S3 ✓"
}

# Warm CDN cache
warm_cache() {
    if [ "$WARM_CACHE" != "true" ]; then
        info "Skipping cache warming (WARM_CACHE=false)"
        return 0
    fi

    log "Warming CDN cache..."

    local cache_warmer="$CDN_DIR/cache-warming/cache-warmer.js"
    local config_file="$CDN_DIR/cache-warming/cache-warming-config.json"

    # Create config if it doesn't exist
    if [ ! -f "$config_file" ]; then
        node "$cache_warmer" init "$config_file"
    fi

    # Update base URL in config based on environment
    local base_url
    case "$ENVIRONMENT" in
        "production")
            base_url="https://brain-researcher.com"
            ;;
        "staging")
            base_url="https://staging.brain-researcher.com"
            ;;
        *)
            base_url="http://localhost:3000"
            ;;
    esac

    # Warm the cache
    CDN_BASE_URL="$base_url" node "$cache_warmer" warm "$config_file"

    log "Cache warming complete ✓"
}

# Start performance monitoring
start_monitoring() {
    if [ "$START_MONITORING" != "true" ]; then
        info "Skipping monitoring startup (START_MONITORING=false)"
        return 0
    fi

    log "Starting performance monitoring..."

    local monitor_script="$CDN_DIR/monitoring/performance-monitor.js"

    # Start monitoring in background
    nohup node "$monitor_script" > "$CDN_DIR/logs/monitor.log" 2>&1 &
    local monitor_pid=$!

    echo "$monitor_pid" > "$CDN_DIR/monitor.pid"

    log "Performance monitoring started (PID: $monitor_pid) ✓"
}

# Validate deployment
validate_deployment() {
    log "Validating deployment..."

    local base_url
    case "$ENVIRONMENT" in
        "production")
            base_url="https://brain-researcher.com"
            ;;
        "staging")
            base_url="https://staging.brain-researcher.com"
            ;;
        *)
            base_url="http://localhost"
            ;;
    esac

    # Test endpoints
    local endpoints=(
        "$base_url"
        "$base_url/api/health"
        "$base_url/static/css/main.css"
    )

    for endpoint in "${endpoints[@]}"; do
        info "Testing $endpoint"

        if curl -sf "$endpoint" > /dev/null; then
            log "✓ $endpoint is accessible"
        else
            error "✗ $endpoint is not accessible"
        fi
    done

    # Test security headers
    local security_test
    security_test=$(curl -sI "$base_url" | grep -i "x-frame-options\|strict-transport-security\|x-content-type-options" | wc -l)

    if [ "$security_test" -ge 2 ]; then
        log "✓ Security headers are present"
    else
        warn "⚠ Security headers may be missing"
    fi

    log "Deployment validation complete ✓"
}

# Generate deployment report
generate_report() {
    log "Generating deployment report..."

    local report_file="$CDN_DIR/deployment-report-$(date +%Y%m%d-%H%M%S).json"

    cat > "$report_file" <<EOF
{
    "deployment": {
        "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
        "environment": "$ENVIRONMENT",
        "version": "$(git rev-parse HEAD 2>/dev/null || echo "unknown")",
        "components": {
            "cloudfront": $DEPLOY_CLOUDFRONT,
            "nginx": $DEPLOY_NGINX,
            "cache_warming": $WARM_CACHE,
            "monitoring": $START_MONITORING
        }
    },
    "configuration": {
        "aws_region": "$AWS_REGION",
        "environment": "$ENVIRONMENT"
    },
    "status": "completed",
    "duration_seconds": $SECONDS
}
EOF

    log "Deployment report saved: $report_file ✓"
}

# Cleanup function
cleanup() {
    log "Cleaning up temporary files..."
    # Add cleanup logic here if needed
}

# Signal handlers
trap cleanup EXIT
trap 'error "Deployment interrupted"' INT TERM

# Usage information
usage() {
    cat <<EOF
Brain Researcher CDN Deployment Script

Usage: $0 [OPTIONS]

Options:
    -e, --environment ENV       Environment (development|staging|production) [default: production]
    -r, --region REGION         AWS region [default: us-east-1]
    --skip-cloudfront          Skip CloudFront deployment
    --skip-nginx               Skip Nginx deployment
    --skip-cache-warming       Skip cache warming
    --skip-monitoring          Skip monitoring startup
    --auto-approve             Auto-approve Terraform changes
    -h, --help                 Show this help message

Environment Variables:
    AWS_REGION                 AWS region
    ENVIRONMENT               Environment name
    DEPLOY_CLOUDFRONT         Deploy CloudFront (true/false)
    DEPLOY_NGINX              Deploy Nginx (true/false)
    WARM_CACHE                Warm cache after deployment (true/false)
    START_MONITORING          Start monitoring after deployment (true/false)
    AUTO_APPROVE              Auto-approve Terraform changes (true/false)

Examples:
    $0                        # Deploy to production with all components
    $0 -e development         # Deploy to development environment
    $0 --skip-cloudfront      # Deploy without CloudFront
    $0 --auto-approve         # Deploy with auto-approval

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--environment)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -r|--region)
            AWS_REGION="$2"
            shift 2
            ;;
        --skip-cloudfront)
            DEPLOY_CLOUDFRONT="false"
            shift
            ;;
        --skip-nginx)
            DEPLOY_NGINX="false"
            shift
            ;;
        --skip-cache-warming)
            WARM_CACHE="false"
            shift
            ;;
        --skip-monitoring)
            START_MONITORING="false"
            shift
            ;;
        --auto-approve)
            AUTO_APPROVE="true"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            ;;
    esac
done

# Main deployment flow
main() {
    log "Starting Brain Researcher CDN deployment..."
    log "Environment: $ENVIRONMENT"
    log "AWS Region: $AWS_REGION"

    check_dependencies
    setup_directories

    if [ "$ENVIRONMENT" = "development" ]; then
        generate_ssl_certs
    fi

    build_nextjs_app
    optimize_images
    deploy_terraform
    deploy_nginx
    upload_static_assets
    warm_cache
    start_monitoring
    validate_deployment
    generate_report

    log "🎉 CDN deployment completed successfully!"
    log "Total deployment time: ${SECONDS}s"

    if [ "$START_MONITORING" = "true" ]; then
        info "Performance monitoring is running in background"
        info "View logs: tail -f $CDN_DIR/logs/monitor.log"
        info "Stop monitoring: kill \$(cat $CDN_DIR/monitor.pid)"
    fi
}

# Run main function
main "$@"
