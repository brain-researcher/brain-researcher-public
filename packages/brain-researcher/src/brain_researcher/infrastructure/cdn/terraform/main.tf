# Brain Researcher CloudFront CDN Configuration
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# S3 Bucket for static assets
resource "aws_s3_bucket" "brain_researcher_static" {
  bucket = var.static_bucket_name

  tags = {
    Name        = "Brain Researcher Static Assets"
    Environment = var.environment
    Project     = "brain-researcher"
  }
}

resource "aws_s3_bucket_public_access_block" "brain_researcher_static" {
  bucket = aws_s3_bucket.brain_researcher_static.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "brain_researcher_static" {
  bucket = aws_s3_bucket.brain_researcher_static.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "brain_researcher_static" {
  bucket = aws_s3_bucket.brain_researcher_static.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "brain_researcher_static" {
  bucket = aws_s3_bucket.brain_researcher_static.id

  rule {
    id     = "static_assets_cleanup"
    status = "Enabled"

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# CloudFront Origin Access Control
resource "aws_cloudfront_origin_access_control" "brain_researcher_oac" {
  name                              = "brain-researcher-oac"
  description                       = "OAC for Brain Researcher S3 static assets"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# CloudFront Response Headers Policy
resource "aws_cloudfront_response_headers_policy" "brain_researcher_security" {
  name    = "brain-researcher-security-headers"
  comment = "Security headers for Brain Researcher"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
    }
  }

  custom_headers_config {
    items {
      header   = "X-Content-Security-Policy"
      override = false
      value = join("; ", [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data: blob: https:",
        "connect-src 'self' https://api.openai.com wss:",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'"
      ])
    }
    
    items {
      header   = "X-Brain-Researcher"
      override = false
      value    = "v1.0"
    }
    
    items {
      header   = "Permissions-Policy"
      override = false
      value    = "geolocation=(), microphone=(), camera=(), payment=(), usb=(), magnetometer=(), gyroscope=()"
    }
  }
}

# CloudFront Cache Policy for API responses
resource "aws_cloudfront_cache_policy" "brain_researcher_api_cache" {
  name        = "brain-researcher-api-cache"
  comment     = "Cache policy for Brain Researcher API responses"
  default_ttl = 300
  max_ttl     = 31536000
  min_ttl     = 0

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true

    query_strings_config {
      query_string_behavior = "whitelist"
      query_strings {
        items = ["query", "limit", "offset", "format", "include"]
      }
    }

    headers_config {
      header_behavior = "whitelist"
      headers {
        items = ["Authorization", "Accept", "Content-Type"]
      }
    }

    cookies_config {
      cookie_behavior = "none"
    }
  }
}

# CloudFront Cache Policy for static assets
resource "aws_cloudfront_cache_policy" "brain_researcher_static_cache" {
  name        = "brain-researcher-static-cache"
  comment     = "Cache policy for Brain Researcher static assets"
  default_ttl = 86400
  max_ttl     = 31536000
  min_ttl     = 0

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true

    query_strings_config {
      query_string_behavior = "none"
    }

    headers_config {
      header_behavior = "none"
    }

    cookies_config {
      cookie_behavior = "none"
    }
  }
}

# CloudFront Distribution
resource "aws_cloudfront_distribution" "brain_researcher_cdn" {
  comment             = "Brain Researcher CDN Distribution"
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  price_class         = var.cloudfront_price_class
  web_acl_id         = var.web_acl_id

  # S3 Origin for static assets
  origin {
    domain_name              = aws_s3_bucket.brain_researcher_static.bucket_regional_domain_name
    origin_id                = "S3-${aws_s3_bucket.brain_researcher_static.bucket}"
    origin_access_control_id = aws_cloudfront_origin_access_control.brain_researcher_oac.id

    custom_header {
      name  = "X-Origin-Verify"
      value = var.origin_verify_token
    }
  }

  # Application Origin (Next.js app)
  origin {
    domain_name = var.app_domain_name
    origin_id   = "AppOrigin"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }

    custom_header {
      name  = "X-Origin-Verify"
      value = var.origin_verify_token
    }
  }

  # API Origin (Orchestrator)
  origin {
    domain_name = var.api_domain_name
    origin_id   = "APIOrigin"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }

    custom_header {
      name  = "X-Origin-Verify"
      value = var.origin_verify_token
    }

    origin_request_policy_id = aws_cloudfront_origin_request_policy.brain_researcher_api.id
  }

  # Static assets behavior
  ordered_cache_behavior {
    path_pattern           = "/static/*"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "S3-${aws_s3_bucket.brain_researcher_static.bucket}"
    cache_policy_id        = aws_cloudfront_cache_policy.brain_researcher_static_cache.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.brain_researcher_security.id
    viewer_protocol_policy = "redirect-to-https"
    compress               = true
  }

  # Next.js assets behavior
  ordered_cache_behavior {
    path_pattern           = "/_next/*"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "AppOrigin"
    cache_policy_id        = aws_cloudfront_cache_policy.brain_researcher_static_cache.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.brain_researcher_security.id
    viewer_protocol_policy = "redirect-to-https"
    compress               = true
  }

  # API behavior
  ordered_cache_behavior {
    path_pattern           = "/api/*"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "APIOrigin"
    cache_policy_id        = aws_cloudfront_cache_policy.brain_researcher_api_cache.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.brain_researcher_security.id
    viewer_protocol_policy = "redirect-to-https"
    compress               = true
  }

  # WebSocket behavior (no caching)
  ordered_cache_behavior {
    path_pattern           = "/ws/*"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "APIOrigin"
    cache_policy_id        = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # Managed-CachingDisabled
    viewer_protocol_policy = "redirect-to-https"
    compress               = false
  }

  # Default behavior
  default_cache_behavior {
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "AppOrigin"
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.brain_researcher_security.id
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.security_headers.arn
    }

    function_association {
      event_type   = "viewer-response"
      function_arn = aws_cloudfront_function.performance_headers.arn
    }
  }

  # Geographic restrictions
  restrictions {
    geo_restriction {
      restriction_type = var.geo_restriction_type
      locations        = var.geo_restriction_locations
    }
  }

  # SSL Certificate
  viewer_certificate {
    acm_certificate_arn            = var.ssl_certificate_arn
    ssl_support_method             = "sni-only"
    minimum_protocol_version       = "TLSv1.2_2021"
    cloudfront_default_certificate = var.ssl_certificate_arn == null
  }

  # Aliases
  aliases = var.domain_aliases

  # Logging
  logging_config {
    include_cookies = false
    bucket         = aws_s3_bucket.brain_researcher_logs.bucket_domain_name
    prefix         = "cdn-logs/"
  }

  # Custom error responses
  dynamic "custom_error_response" {
    for_each = [
      { error_code = 403, response_code = 200, response_page_path = "/404" },
      { error_code = 404, response_code = 200, response_page_path = "/404" },
      { error_code = 500, response_code = 500, response_page_path = "/500" },
      { error_code = 502, response_code = 502, response_page_path = "/502" },
      { error_code = 503, response_code = 503, response_page_path = "/503" },
      { error_code = 504, response_code = 504, response_page_path = "/504" }
    ]
    
    content {
      error_code            = custom_error_response.value.error_code
      response_code         = custom_error_response.value.response_code
      response_page_path    = custom_error_response.value.response_page_path
      error_caching_min_ttl = 300
    }
  }

  tags = {
    Name        = "Brain Researcher CDN"
    Environment = var.environment
    Project     = "brain-researcher"
  }

  depends_on = [
    aws_s3_bucket_policy.brain_researcher_static,
    aws_cloudfront_function.security_headers,
    aws_cloudfront_function.performance_headers
  ]
}

# Origin Request Policy for API
resource "aws_cloudfront_origin_request_policy" "brain_researcher_api" {
  name    = "brain-researcher-api-request"
  comment = "Origin request policy for Brain Researcher API"

  query_strings_config {
    query_string_behavior = "all"
  }

  headers_config {
    header_behavior = "whitelist"
    headers {
      items = [
        "Authorization",
        "Accept",
        "Content-Type",
        "User-Agent",
        "X-Forwarded-For",
        "CloudFront-Viewer-Country",
        "CloudFront-Is-Mobile-Viewer",
        "CloudFront-Is-Desktop-Viewer"
      ]
    }
  }

  cookies_config {
    cookie_behavior = "none"
  }
}

# CloudFront Functions
resource "aws_cloudfront_function" "security_headers" {
  name    = "brain-researcher-security-headers"
  runtime = "cloudfront-js-1.0"
  comment = "Add security headers to Brain Researcher responses"
  publish = true
  code    = file("${path.module}/functions/security-headers.js")
}

resource "aws_cloudfront_function" "performance_headers" {
  name    = "brain-researcher-performance-headers"
  runtime = "cloudfront-js-1.0"
  comment = "Add performance headers to Brain Researcher responses"
  publish = true
  code    = file("${path.module}/functions/performance-headers.js")
}

# S3 Bucket Policy
resource "aws_s3_bucket_policy" "brain_researcher_static" {
  bucket = aws_s3_bucket.brain_researcher_static.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontServicePrincipal"
        Effect    = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.brain_researcher_static.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.brain_researcher_cdn.arn
          }
        }
      }
    ]
  })
}

# S3 Bucket for logs
resource "aws_s3_bucket" "brain_researcher_logs" {
  bucket = "${var.static_bucket_name}-logs"

  tags = {
    Name        = "Brain Researcher CDN Logs"
    Environment = var.environment
    Project     = "brain-researcher"
  }
}

resource "aws_s3_bucket_public_access_block" "brain_researcher_logs" {
  bucket = aws_s3_bucket.brain_researcher_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# CloudWatch alarms
resource "aws_cloudwatch_metric_alarm" "high_4xx_error_rate" {
  alarm_name          = "brain-researcher-high-4xx-error-rate"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "4xxErrorRate"
  namespace           = "AWS/CloudFront"
  period              = "300"
  statistic           = "Average"
  threshold           = "10"
  alarm_description   = "This metric monitors 4xx error rate"
  alarm_actions       = [var.sns_topic_arn]

  dimensions = {
    DistributionId = aws_cloudfront_distribution.brain_researcher_cdn.id
  }
}

resource "aws_cloudwatch_metric_alarm" "high_5xx_error_rate" {
  alarm_name          = "brain-researcher-high-5xx-error-rate"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "5xxErrorRate"
  namespace           = "AWS/CloudFront"
  period              = "300"
  statistic           = "Average"
  threshold           = "5"
  alarm_description   = "This metric monitors 5xx error rate"
  alarm_actions       = [var.sns_topic_arn]

  dimensions = {
    DistributionId = aws_cloudfront_distribution.brain_researcher_cdn.id
  }
}

resource "aws_cloudwatch_metric_alarm" "high_origin_latency" {
  alarm_name          = "brain-researcher-high-origin-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "3"
  metric_name         = "OriginLatency"
  namespace           = "AWS/CloudFront"
  period              = "300"
  statistic           = "Average"
  threshold           = "5000"
  alarm_description   = "This metric monitors origin latency"
  alarm_actions       = [var.sns_topic_arn]

  dimensions = {
    DistributionId = aws_cloudfront_distribution.brain_researcher_cdn.id
  }
}