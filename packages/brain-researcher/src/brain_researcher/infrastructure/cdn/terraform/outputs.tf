# Outputs for Brain Researcher CDN Infrastructure

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID"
  value       = aws_cloudfront_distribution.brain_researcher_cdn.id
}

output "cloudfront_distribution_arn" {
  description = "CloudFront distribution ARN"
  value       = aws_cloudfront_distribution.brain_researcher_cdn.arn
}

output "cloudfront_domain_name" {
  description = "CloudFront distribution domain name"
  value       = aws_cloudfront_distribution.brain_researcher_cdn.domain_name
}

output "cloudfront_hosted_zone_id" {
  description = "CloudFront distribution hosted zone ID"
  value       = aws_cloudfront_distribution.brain_researcher_cdn.hosted_zone_id
}

output "s3_bucket_name" {
  description = "S3 bucket name for static assets"
  value       = aws_s3_bucket.brain_researcher_static.bucket
}

output "s3_bucket_arn" {
  description = "S3 bucket ARN for static assets"
  value       = aws_s3_bucket.brain_researcher_static.arn
}

output "s3_bucket_domain_name" {
  description = "S3 bucket domain name"
  value       = aws_s3_bucket.brain_researcher_static.bucket_domain_name
}

output "s3_logs_bucket_name" {
  description = "S3 bucket name for CloudFront logs"
  value       = aws_s3_bucket.brain_researcher_logs.bucket
}

output "origin_access_control_id" {
  description = "CloudFront Origin Access Control ID"
  value       = aws_cloudfront_origin_access_control.brain_researcher_oac.id
}

output "cache_policy_static_id" {
  description = "CloudFront cache policy ID for static assets"
  value       = aws_cloudfront_cache_policy.brain_researcher_static_cache.id
}

output "cache_policy_api_id" {
  description = "CloudFront cache policy ID for API responses"
  value       = aws_cloudfront_cache_policy.brain_researcher_api_cache.id
}

output "response_headers_policy_id" {
  description = "CloudFront response headers policy ID"
  value       = aws_cloudfront_response_headers_policy.brain_researcher_security.id
}

output "origin_request_policy_id" {
  description = "CloudFront origin request policy ID for API"
  value       = aws_cloudfront_origin_request_policy.brain_researcher_api.id
}

output "security_headers_function_arn" {
  description = "CloudFront function ARN for security headers"
  value       = aws_cloudfront_function.security_headers.arn
}

output "performance_headers_function_arn" {
  description = "CloudFront function ARN for performance headers"
  value       = aws_cloudfront_function.performance_headers.arn
}

output "cloudwatch_alarms" {
  description = "CloudWatch alarm names"
  value = {
    high_4xx_error_rate = aws_cloudwatch_metric_alarm.high_4xx_error_rate.alarm_name
    high_5xx_error_rate = aws_cloudwatch_metric_alarm.high_5xx_error_rate.alarm_name
    high_origin_latency = aws_cloudwatch_metric_alarm.high_origin_latency.alarm_name
  }
}

# Configuration outputs for integration
output "cdn_config" {
  description = "CDN configuration for application integration"
  value = {
    distribution_id     = aws_cloudfront_distribution.brain_researcher_cdn.id
    domain_name        = aws_cloudfront_distribution.brain_researcher_cdn.domain_name
    s3_bucket          = aws_s3_bucket.brain_researcher_static.bucket
    s3_region          = aws_s3_bucket.brain_researcher_static.region
    origin_verify_token = var.origin_verify_token
  }
  sensitive = true
}