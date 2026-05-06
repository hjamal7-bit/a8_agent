"""
CLI for a8_agent cadence operations.

Usage:
  a8_cadence regenerate <template_id>  - Regenerate drafts for all active instances of a template
  a8_cadence regenerate <instance_id> --instance  - Regenerate drafts for a single instance
  a8_cadence status  - Check health of a8_agent service
"""

import asyncio
import sys
import os
from typing import Optional

import click
import httpx
from dotenv import load_dotenv

load_dotenv()

A8_AGENT_URL = os.getenv("A8_AGENT_URL", "http://127.0.0.1:8788")
DATABASE_URL = os.getenv("A8_DATABASE_URL", "postgresql://localhost/a8")


@click.group()
def cli():
    """a8_agent CLI - Cadence draft operations."""
    pass


@cli.command()
@click.argument("template_id")
@click.option("--instance", is_flag=True, help="Treat ID as cadence_instance_id instead of template_id")
@click.option("--force", is_flag=True, help="Force regeneration even if drafts exist")
def regenerate(template_id: str, instance: bool, force: bool):
    """
    Regenerate cadence drafts.
    
    By default, regenerates all active instances for a template.
    Use --instance to regenerate a single cadence instance.
    Use --force to skip draft existence checks.
    """
    try:
        if instance:
            endpoint = f"{A8_AGENT_URL}/cadence/{template_id}/generate-on-enroll"
            params = {"force": force}
        else:
            endpoint = f"{A8_AGENT_URL}/cadence/template/{template_id}/regenerate"
            params = {"force": force}
        
        with httpx.Client(timeout=30.0) as client:
            response = client.post(endpoint, params=params)
            response.raise_for_status()
            
        result = response.json()
        
        if "generated_count" in result:
            click.secho(
                f"✓ Generated {result['generated_count']} drafts",
                fg="green"
            )
        
        if "instances_processed" in result:
            click.secho(
                f"✓ Processed {result['instances_processed']} instances",
                fg="green"
            )
        
        if "message" in result:
            click.echo(f"  {result['message']}")
        
        # Show details if available
        if "details" in result:
            for detail in result["details"]:
                click.echo(f"  - {detail}")
        
        sys.exit(0)
    
    except httpx.HTTPError as e:
        click.secho(f"✗ API error: {e}", fg="red")
        sys.exit(1)
    except Exception as e:
        click.secho(f"✗ Error: {e}", fg="red")
        sys.exit(1)


@cli.command()
def status():
    """Check health and status of a8_agent service."""
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{A8_AGENT_URL}/health")
            response.raise_for_status()
        
        health = response.json()
        
        click.secho("✓ a8_agent is running", fg="green")
        click.echo(f"  Service: {health.get('service', 'unknown')}")
        click.echo(f"  Status: {health.get('status', 'unknown')}")
        
        if "version" in health:
            click.echo(f"  Version: {health['version']}")
        
        sys.exit(0)
    
    except httpx.ConnectError:
        click.secho(f"✗ Cannot connect to a8_agent at {A8_AGENT_URL}", fg="red")
        click.echo("  Is the service running? Check: launchctl list | grep cadence-agent")
        sys.exit(1)
    except httpx.HTTPError as e:
        click.secho(f"✗ Service error: {e}", fg="red")
        sys.exit(1)


@cli.command()
def logs():
    """Tail a8_agent service logs."""
    log_path = os.path.expanduser("~/.a8/logs/cadence-agent.log")
    
    if not os.path.exists(log_path):
        click.secho(f"✗ Log file not found: {log_path}", fg="red")
        sys.exit(1)
    
    try:
        os.execvp("tail", ["tail", "-f", log_path])
    except Exception as e:
        click.secho(f"✗ Error: {e}", fg="red")
        sys.exit(1)


if __name__ == "__main__":
    cli()
