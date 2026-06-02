#!/usr/bin/env python3
"""
CLI tool for Brain Researcher API Gateway management.

Provides command-line interface for:
- Starting/stopping the gateway
- Managing service registrations
- Viewing health and metrics
- Cache management
- Rate limiting configuration
- Testing connectivity
"""

import asyncio
import json
import sys
from pathlib import Path

import click
import httpx
import redis
import uvicorn
import yaml

from .cache_manager import CacheManager
from .gateway import create_gateway
from .health_monitor import HealthMonitor
from .service_registry import Service, ServiceRegistry


@click.group()
@click.option("--config", "-c", help="Configuration file path")
@click.option("--debug/--no-debug", default=False, help="Enable debug mode")
@click.pass_context
def cli(ctx, config, debug):
    """Brain Researcher API Gateway CLI."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = config
    ctx.obj["debug"] = debug


@cli.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8080, help="Port to bind to")
@click.option("--reload/--no-reload", default=False, help="Enable auto-reload")
@click.pass_context
def serve(ctx, host, port, reload):
    """Start the API Gateway server."""
    config_path = ctx.obj.get("config")
    debug = ctx.obj.get("debug", False)

    click.echo(f"Starting API Gateway on {host}:{port}")
    if config_path:
        click.echo(f"Using config: {config_path}")

    # Create gateway app
    try:
        app = create_gateway(config_path)

        # Start server
        uvicorn.run(
            app, host=host, port=port, debug=debug, reload=reload, access_log=debug
        )

    except Exception as e:
        click.echo(f"Failed to start gateway: {e}", err=True)
        sys.exit(1)


@cli.group()
def services():
    """Service management commands."""
    pass


@services.command("list")
@click.option("--format", type=click.Choice(["table", "json", "yaml"]), default="table")
@click.pass_context
def list_services(ctx, format):
    """List registered services."""
    try:
        # Connect to Redis
        redis_client = redis.from_url("redis://localhost:6379/0")
        registry = ServiceRegistry(redis_client)

        # Get services
        services = asyncio.run(registry.get_all_services())

        if format == "json":
            click.echo(
                json.dumps(
                    {name: service.dict() for name, service in services.items()},
                    indent=2,
                    default=str,
                )
            )
        elif format == "yaml":
            click.echo(
                yaml.dump(
                    {name: service.dict() for name, service in services.items()},
                    default_flow_style=False,
                )
            )
        else:
            # Table format
            click.echo("\nRegistered Services:")
            click.echo("-" * 80)
            click.echo(f"{'Name':<15} {'URL':<30} {'Status':<10} {'Instances':<10}")
            click.echo("-" * 80)

            for name, service in services.items():
                status = "Unknown"
                if service.instances:
                    healthy_count = sum(
                        1
                        for inst in service.instances
                        if inst.health.status.value == "healthy"
                    )
                    if healthy_count == len(service.instances):
                        status = "Healthy"
                    elif healthy_count > 0:
                        status = "Partial"
                    else:
                        status = "Unhealthy"

                click.echo(
                    f"{name:<15} {service.url:<30} {status:<10} {len(service.instances):<10}"
                )

    except Exception as e:
        click.echo(f"Error listing services: {e}", err=True)
        sys.exit(1)


@services.command("register")
@click.argument("name")
@click.argument("url")
@click.option("--health-path", default="/health", help="Health check path")
@click.option("--version", default="1.0.0", help="Service version")
@click.option("--description", help="Service description")
@click.option("--tags", help="Comma-separated tags")
def register_service(name, url, health_path, version, description, tags):
    """Register a new service."""
    try:
        # Connect to Redis
        redis_client = redis.from_url("redis://localhost:6379/0")
        registry = ServiceRegistry(redis_client)

        # Parse tags
        tag_list = [tag.strip() for tag in tags.split(",")] if tags else []

        # Create service
        service = Service(
            name=name,
            url=url,
            health_check_path=health_path,
            version=version,
            description=description,
            tags=tag_list,
        )

        # Register service
        success = asyncio.run(registry.register(service))

        if success:
            click.echo(f"Successfully registered service '{name}'")
        else:
            click.echo(f"Failed to register service '{name}'", err=True)
            sys.exit(1)

    except Exception as e:
        click.echo(f"Error registering service: {e}", err=True)
        sys.exit(1)


@services.command("deregister")
@click.argument("name")
@click.option("--instance-id", help="Specific instance ID to deregister")
def deregister_service(name, instance_id):
    """Deregister a service or instance."""
    try:
        # Connect to Redis
        redis_client = redis.from_url("redis://localhost:6379/0")
        registry = ServiceRegistry(redis_client)

        # Deregister service/instance
        success = asyncio.run(registry.deregister(name, instance_id))

        if success:
            if instance_id:
                click.echo(f"Successfully deregistered instance '{name}/{instance_id}'")
            else:
                click.echo(f"Successfully deregistered service '{name}'")
        else:
            click.echo(f"Failed to deregister '{name}'", err=True)
            sys.exit(1)

    except Exception as e:
        click.echo(f"Error deregistering service: {e}", err=True)
        sys.exit(1)


@cli.group()
def health():
    """Health monitoring commands."""
    pass


@health.command("check")
@click.option("--service", help="Check specific service")
@click.option("--format", type=click.Choice(["table", "json"]), default="table")
def check_health(service, format):
    """Check service health."""
    try:
        # Connect to Redis
        redis_client = redis.from_url("redis://localhost:6379/0")
        registry = ServiceRegistry(redis_client)
        monitor = HealthMonitor(registry)

        if service:
            # Check specific service
            service_obj = asyncio.run(registry.get_service(service))
            if not service_obj:
                click.echo(f"Service '{service}' not found", err=True)
                sys.exit(1)

            health_results = asyncio.run(monitor.check_service_health(service_obj))

            if format == "json":
                click.echo(
                    json.dumps(
                        {
                            service: {
                                inst_id: health.dict()
                                for inst_id, health in health_results.items()
                            }
                        },
                        indent=2,
                        default=str,
                    )
                )
            else:
                click.echo(f"\nHealth Check Results for '{service}':")
                click.echo("-" * 60)
                for inst_id, health in health_results.items():
                    status_color = (
                        "green" if health.status.value == "healthy" else "red"
                    )
                    click.echo(f"Instance {inst_id}: ", nl=False)
                    click.secho(health.status.value.upper(), fg=status_color)
                    if health.response_time_ms:
                        click.echo(f"  Response Time: {health.response_time_ms:.2f}ms")
                    if health.error_message:
                        click.echo(f"  Error: {health.error_message}")
        else:
            # Check all services
            asyncio.run(monitor.check_all_services())
            services = asyncio.run(registry.get_all_services())

            if format == "json":
                health_data = {}
                for name, svc in services.items():
                    health_data[name] = {
                        inst.instance_id: inst.health.dict() for inst in svc.instances
                    }
                click.echo(json.dumps(health_data, indent=2, default=str))
            else:
                click.echo("\nService Health Summary:")
                click.echo("-" * 60)
                for name, svc in services.items():
                    healthy_count = sum(
                        1
                        for inst in svc.instances
                        if inst.health.status.value == "healthy"
                    )
                    total_count = len(svc.instances)

                    status_text = f"{healthy_count}/{total_count} healthy"
                    if healthy_count == total_count and total_count > 0:
                        color = "green"
                    elif healthy_count > 0:
                        color = "yellow"
                    else:
                        color = "red"

                    click.echo(f"{name:<20} ", nl=False)
                    click.secho(status_text, fg=color)

    except Exception as e:
        click.echo(f"Error checking health: {e}", err=True)
        sys.exit(1)


@cli.group()
def cache():
    """Cache management commands."""
    pass


@cache.command("stats")
@click.option("--format", type=click.Choice(["table", "json"]), default="table")
def cache_stats(format):
    """Show cache statistics."""
    try:
        # Connect to Redis
        redis_client = redis.from_url("redis://localhost:6379/0")
        cache_manager = CacheManager(redis_client)

        stats = asyncio.run(cache_manager.get_cache_stats())

        if format == "json":
            click.echo(json.dumps(stats.dict(), indent=2))
        else:
            click.echo("\nCache Statistics:")
            click.echo("-" * 40)
            click.echo(f"Total Requests:    {stats.total_requests}")
            click.echo(f"Cache Hits:        {stats.cache_hits}")
            click.echo(f"Cache Misses:      {stats.cache_misses}")
            click.echo(f"Hit Rate:          {stats.hit_rate:.2f}%")
            click.echo(
                f"Total Size:        {stats.total_size_bytes / 1024 / 1024:.2f} MB"
            )
            click.echo(f"Entry Count:       {stats.entry_count}")

    except Exception as e:
        click.echo(f"Error getting cache stats: {e}", err=True)
        sys.exit(1)


@cache.command("clear")
@click.confirmation_option(prompt="Are you sure you want to clear the cache?")
def clear_cache():
    """Clear all cached entries."""
    try:
        # Connect to Redis
        redis_client = redis.from_url("redis://localhost:6379/0")
        cache_manager = CacheManager(redis_client)

        cleared_count = asyncio.run(cache_manager.clear_cache())
        click.echo(f"Cleared {cleared_count} cache entries")

    except Exception as e:
        click.echo(f"Error clearing cache: {e}", err=True)
        sys.exit(1)


@cache.command("invalidate")
@click.option("--pattern", help="Cache key pattern to invalidate")
@click.option("--path", help="Request path to invalidate")
@click.option("--service", help="Service to invalidate")
def invalidate_cache(pattern, path, service):
    """Invalidate cache entries."""
    if not any([pattern, path, service]):
        click.echo("Must specify --pattern, --path, or --service", err=True)
        sys.exit(1)

    try:
        # Connect to Redis
        redis_client = redis.from_url("redis://localhost:6379/0")
        cache_manager = CacheManager(redis_client)

        invalidated_count = asyncio.run(
            cache_manager.invalidate_cache(pattern=pattern, path=path, service=service)
        )
        click.echo(f"Invalidated {invalidated_count} cache entries")

    except Exception as e:
        click.echo(f"Error invalidating cache: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--gateway-url", default="http://localhost:8080", help="Gateway URL")
@click.option("--timeout", default=10, help="Request timeout")
def test(gateway_url, timeout):
    """Test gateway connectivity and basic functionality."""
    click.echo(f"Testing API Gateway at {gateway_url}")

    async def run_tests():
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Test health endpoint
            try:
                response = await client.get(f"{gateway_url}/health")
                if response.status_code == 200:
                    click.secho("✓ Health check: PASS", fg="green")
                else:
                    click.secho(
                        f"✗ Health check: FAIL ({response.status_code})", fg="red"
                    )
            except Exception as e:
                click.secho(f"✗ Health check: ERROR ({e})", fg="red")

            # Test services endpoint
            try:
                response = await client.get(f"{gateway_url}/services")
                if response.status_code == 200:
                    services_data = response.json()
                    click.secho(
                        f"✓ Services endpoint: PASS ({len(services_data)} services)",
                        fg="green",
                    )
                else:
                    click.secho(
                        f"✗ Services endpoint: FAIL ({response.status_code})", fg="red"
                    )
            except Exception as e:
                click.secho(f"✗ Services endpoint: ERROR ({e})", fg="red")

            # Test metrics endpoint
            try:
                response = await client.get(f"{gateway_url}/metrics")
                if response.status_code == 200:
                    click.secho("✓ Metrics endpoint: PASS", fg="green")
                else:
                    click.secho(
                        f"✗ Metrics endpoint: FAIL ({response.status_code})", fg="red"
                    )
            except Exception as e:
                click.secho(f"✗ Metrics endpoint: ERROR ({e})", fg="red")

    try:
        asyncio.run(run_tests())
    except Exception as e:
        click.echo(f"Test error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--output", "-o", help="Output file path")
@click.option("--format", type=click.Choice(["yaml", "json"]), default="yaml")
def config_template(output, format):
    """Generate configuration template."""
    template_config = {
        "gateway": {"port": 8080, "host": "0.0.0.0", "debug": False},
        "redis": {"url": "redis://localhost:6379/0"},
        "services": [
            {
                "name": "example-service",
                "url": "http://localhost:8081",
                "health_check_path": "/health",
            }
        ],
        "routes": [
            {
                "name": "example-route",
                "path": "/api/example/**",
                "service": "example-service",
                "methods": ["GET", "POST"],
            }
        ],
    }

    if format == "json":
        content = json.dumps(template_config, indent=2)
    else:
        content = yaml.dump(template_config, default_flow_style=False)

    if output:
        Path(output).write_text(content)
        click.echo(f"Configuration template written to {output}")
    else:
        click.echo(content)


if __name__ == "__main__":
    cli()
