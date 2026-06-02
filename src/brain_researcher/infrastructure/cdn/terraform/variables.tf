# Variables for Brain Researcher CDN Infrastructure

variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

variable "static_bucket_name" {
  description = "Name of the S3 bucket for static assets"
  type        = string
  default     = "brain-researcher-static-assets"
}

variable "app_domain_name" {
  description = "Domain name of the Next.js application"
  type        = string
  default     = "app.brain-researcher.com"
}

variable "api_domain_name" {
  description = "Domain name of the API orchestrator"
  type        = string
  default     = "api.brain-researcher.com"
}

variable "domain_aliases" {
  description = "List of domain aliases for CloudFront distribution"
  type        = list(string)
  default     = ["brain-researcher.com", "www.brain-researcher.com"]
}

variable "ssl_certificate_arn" {
  description = "ARN of the SSL certificate in ACM (us-east-1 region)"
  type        = string
  default     = null
}

variable "cloudfront_price_class" {
  description = "CloudFront price class"
  type        = string
  default     = "PriceClass_100"

  validation {
    condition = contains([
      "PriceClass_All",
      "PriceClass_200",
      "PriceClass_100"
    ], var.cloudfront_price_class)
    error_message = "CloudFront price class must be one of: PriceClass_All, PriceClass_200, PriceClass_100."
  }
}

variable "geo_restriction_type" {
  description = "Geographic restriction type"
  type        = string
  default     = "none"

  validation {
    condition     = contains(["none", "whitelist", "blacklist"], var.geo_restriction_type)
    error_message = "Geo restriction type must be one of: none, whitelist, blacklist."
  }
}

variable "geo_restriction_locations" {
  description = "List of country codes for geographic restrictions"
  type        = list(string)
  default     = []
}

variable "web_acl_id" {
  description = "Web ACL ID for AWS WAF (optional)"
  type        = string
  default     = null
}

variable "origin_verify_token" {
  description = "Secret token to verify requests from CloudFront"
  type        = string
  sensitive   = true
  default     = "brain-researcher-verify-token-2024"
}

variable "sns_topic_arn" {
  description = "SNS topic ARN for CloudWatch alarms"
  type        = string
  default     = null
}

variable "enable_real_time_logs" {
  description = "Enable CloudFront real-time logs"
  type        = bool
  default     = false
}

variable "log_retention_days" {
  description = "Number of days to retain CloudFront logs"
  type        = number
  default     = 90
}

variable "cache_default_ttl" {
  description = "Default TTL for cached objects (seconds)"
  type        = number
  default     = 86400
}

variable "cache_max_ttl" {
  description = "Maximum TTL for cached objects (seconds)"
  type        = number
  default     = 31536000
}

variable "enable_compression" {
  description = "Enable gzip compression"
  type        = bool
  default     = true
}

variable "enable_ipv6" {
  description = "Enable IPv6 support"
  type        = bool
  default     = true
}

variable "minimum_protocol_version" {
  description = "Minimum SSL/TLS protocol version"
  type        = string
  default     = "TLSv1.2_2021"
}

variable "custom_headers" {
  description = "Custom headers to add to responses"
  type = map(string)
  default = {
    "X-Frame-Options"           = "DENY"
    "X-Content-Type-Options"    = "nosniff"
    "Referrer-Policy"          = "strict-origin-when-cross-origin"
    "X-XSS-Protection"         = "1; mode=block"
  }
}

variable "allowed_methods" {
  description = "HTTP methods allowed by CloudFront"
  type        = list(string)
  default     = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
}

variable "cached_methods" {
  description = "HTTP methods that CloudFront caches"
  type        = list(string)
  default     = ["GET", "HEAD"]
}

variable "forward_query_string" {
  description = "Forward query strings to origin"
  type        = bool
  default     = true
}

variable "forward_cookies" {
  description = "Cookie forwarding configuration"
  type        = string
  default     = "none"

  validation {
    condition     = contains(["none", "whitelist", "all"], var.forward_cookies)
    error_message = "Forward cookies must be one of: none, whitelist, all."
  }
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default = {
    Project   = "brain-researcher"
    Terraform = "true"
  }
}