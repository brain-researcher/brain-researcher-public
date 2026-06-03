# Cloudflare Terraform Configuration for Brain Researcher
# This configures your domain with optimal CDN, security, and performance settings

terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }
}

# Configure the Cloudflare provider
provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# Variables
variable "cloudflare_api_token" {
  description = "Cloudflare API Token with Zone:Read and Zone:Edit permissions"
  type        = string
  sensitive   = true
}

variable "cloudflare_zone_id" {
  description = "Your Cloudflare Zone ID"
  type        = string
}

variable "domain" {
  description = "Your domain name (e.g., ${PUBLIC_HOSTNAME})"
  type        = string
}

variable "origin_server_ip" {
  description = "IP address of your origin server"
  type        = string
}

# DNS Records
resource "cloudflare_record" "root" {
  zone_id = var.cloudflare_zone_id
  name    = "@"
  value   = var.origin_server_ip
  type    = "A"
  ttl     = 1  # Automatic TTL
  proxied = true  # Orange cloud - traffic goes through Cloudflare
}

resource "cloudflare_record" "www" {
  zone_id = var.cloudflare_zone_id
  name    = "www"
  value   = var.domain
  type    = "CNAME"
  ttl     = 1
  proxied = true
}

resource "cloudflare_record" "api" {
  zone_id = var.cloudflare_zone_id
  name    = "api"
  value   = var.origin_server_ip
  type    = "A"
  ttl     = 1
  proxied = true
}

resource "cloudflare_record" "br-kg" {
  zone_id = var.cloudflare_zone_id
  name    = "kg"
  value   = var.origin_server_ip
  type    = "A"
  ttl     = 1
  proxied = true
}

resource "cloudflare_record" "agent" {
  zone_id = var.cloudflare_zone_id
  name    = "agent"
  value   = var.origin_server_ip
  type    = "A"
  ttl     = 1
  proxied = true
}

# Page Rules for Caching
resource "cloudflare_page_rule" "static_assets" {
  zone_id  = var.cloudflare_zone_id
  target   = "${var.domain}/_next/static/*"
  priority = 1

  actions {
    cache_level = "cache_everything"
    edge_cache_ttl = 31536000  # 1 year for static assets
    browser_cache_ttl = 31536000
  }
}

resource "cloudflare_page_rule" "images" {
  zone_id  = var.cloudflare_zone_id
  target   = "${var.domain}/images/*"
  priority = 2

  actions {
    cache_level = "cache_everything"
    edge_cache_ttl = 2592000  # 30 days for images
    browser_cache_ttl = 604800  # 7 days browser cache
    polish = "lossless"  # Image optimization
    mirage = "on"  # Mobile image optimization
  }
}

resource "cloudflare_page_rule" "api_cache" {
  zone_id  = var.cloudflare_zone_id
  target   = "api.${var.domain}/datasets/*"
  priority = 3

  actions {
    cache_level = "cache_everything"
    edge_cache_ttl = 3600  # 1 hour for API responses
    cache_key_fields {
      query_string {
        include = ["*"]
      }
      header {
        include = ["Authorization"]
      }
    }
  }
}

# SSL/TLS Configuration
resource "cloudflare_zone_settings_override" "ssl_settings" {
  zone_id = var.cloudflare_zone_id

  settings {
    ssl                      = "full"  # Or "strict" if you have valid origin cert
    always_use_https         = "on"
    automatic_https_rewrites = "on"
    min_tls_version         = "1.2"
    tls_1_3                 = "on"

    # Security settings
    security_level          = "medium"
    challenge_ttl          = 1800
    browser_check          = "on"

    # Performance settings
    brotli                 = "on"
    minify {
      css  = "on"
      js   = "on"
      html = "on"
    }

    # Caching
    browser_cache_ttl     = 14400
    always_online         = "on"

    # Additional optimizations
    http2                 = "on"
    http3                 = "on"
    websockets           = "on"
    opportunistic_encryption = "on"

    # Image optimization
    polish               = "lossless"
    webp                = "on"
    image_resizing      = "on"

    # Mobile optimization
    mirage              = "on"
    mobile_redirect {
      mobile_subdomain = ""
      strip_uri       = false
      status         = "off"
    }
  }
}

# WAF Rules
resource "cloudflare_waf_rule" "sql_injection" {
  rule_id = "100000"
  zone_id = var.cloudflare_zone_id
  mode    = "block"
}

resource "cloudflare_waf_rule" "xss" {
  rule_id = "100001"
  zone_id = var.cloudflare_zone_id
  mode    = "block"
}

# Rate Limiting
resource "cloudflare_rate_limit" "api_limit" {
  zone_id   = var.cloudflare_zone_id
  threshold = 50
  period    = 60  # 50 requests per minute

  match {
    request {
      url_pattern = "api.${var.domain}/*"
      methods     = ["POST", "PUT", "DELETE"]
    }
  }

  action {
    mode    = "challenge"
    timeout = 600  # 10 minute timeout
  }
}

# Custom Cache Rules using new Cache Rules API
resource "cloudflare_ruleset" "cache_rules" {
  zone_id = var.cloudflare_zone_id
  name    = "Brain Researcher Cache Rules"
  kind    = "zone"
  phase   = "http_request_cache_settings"

  rules {
    action = "set_cache_settings"
    expression = "(http.request.uri.path matches \"^/_next/static/\")"
    description = "Cache static assets for 1 year"
    action_parameters {
      edge_ttl {
        mode = "override_origin"
        default = 31536000
      }
      browser_ttl {
        mode = "override_origin"
        default = 31536000
      }
      cache_key {
        cache_deception_armor = true
        ignore_query_strings_order = true
      }
    }
  }

  rules {
    action = "set_cache_settings"
    expression = "(http.request.uri.path matches \"^/api/datasets/\")"
    description = "Cache dataset API responses"
    action_parameters {
      edge_ttl {
        mode = "override_origin"
        default = 3600
      }
      cache_key {
        custom_key {
          query_string {
            include = ["*"]
          }
        }
      }
    }
  }
}

# Transform Rules for Headers
resource "cloudflare_ruleset" "transform_rules" {
  zone_id = var.cloudflare_zone_id
  name    = "Brain Researcher Transform Rules"
  kind    = "zone"
  phase   = "http_response_headers_transform"

  rules {
    action = "rewrite"
    expression = "true"
    description = "Add security headers"
    action_parameters {
      headers {
        name      = "X-Frame-Options"
        operation = "set"
        value     = "SAMEORIGIN"
      }
      headers {
        name      = "X-Content-Type-Options"
        operation = "set"
        value     = "nosniff"
      }
      headers {
        name      = "Referrer-Policy"
        operation = "set"
        value     = "strict-origin-when-cross-origin"
      }
      headers {
        name      = "Permissions-Policy"
        operation = "set"
        value     = "camera=(), microphone=(), geolocation=()"
      }
    }
  }
}

# Workers for Edge Computing (Optional)
resource "cloudflare_worker_script" "edge_optimizer" {
  name    = "brain_researcher_edge"
  content = file("${path.module}/workers/edge-optimizer.js")

  plain_text_binding {
    name = "SECRET_KEY"
    text = var.worker_secret_key
  }
}

resource "cloudflare_worker_route" "api_route" {
  zone_id     = var.cloudflare_zone_id
  pattern     = "api.${var.domain}/optimize/*"
  script_name = cloudflare_worker_script.edge_optimizer.name
}

# Outputs
output "nameservers" {
  value = data.cloudflare_zone.main.name_servers
  description = "Cloudflare nameservers for your domain"
}

output "zone_id" {
  value = var.cloudflare_zone_id
  description = "Cloudflare Zone ID"
}