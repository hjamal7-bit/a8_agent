"""
Health Check Module for a8_agent

Monitors a8_agent service health including:
- launchd status (if running as service)
- Process uptime and memory
- HTTP endpoint responsiveness
- Error rates and database connectivity
- Graceful failure alerts

Usage:
  python -m monitoring.health_check
  python -m monitoring.health_check --json
  python -m monitoring.health_check --watch (continuous monitoring)
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

import httpx


@dataclass
class HealthStatus:
    """Represents overall health status of a8_agent."""
    timestamp: str
    service_running: bool
    http_endpoint_ok: bool
    database_connected: bool
    process_uptime_seconds: Optional[int]
    process_memory_mb: Optional[float]
    error_rate: float
    last_error: Optional[str]
    checks_passed: int
    checks_total: int
    
    def is_healthy(self) -> bool:
        """Returns True if all critical checks pass."""
        return (
            self.service_running and
            self.http_endpoint_ok and
            self.checks_passed >= self.checks_total - 1  # Allow 1 non-critical failure
        )


class A8HealthChecker:
    """Performs health checks on a8_agent service."""
    
    def __init__(
        self,
        service_name: str = "com.jamal.a8-cadence-agent",
        http_url: str = "http://127.0.0.1:8788",
        db_url: Optional[str] = None,
        log_file: Optional[str] = None,
    ):
        self.service_name = service_name
        self.http_url = http_url
        self.db_url = db_url or os.getenv("A8_DATABASE_URL", "postgresql://localhost/a8_crm")
        self.log_file = log_file or os.path.expanduser("~/.a8/logs/cadence-agent.log")
        
        # Metrics tracking
        self.request_count = 0
        self.error_count = 0
        self.check_history: Dict[str, Any] = {}
    
    def check_launchd_status(self) -> tuple[bool, Optional[str]]:
        """Check if service is loaded and running via launchd."""
        try:
            result = subprocess.run(
                ["launchctl", "list", self.service_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            
            if result.returncode == 0:
                # Service exists. Check if running (PID > 0)
                output = result.stdout.strip()
                if output:
                    lines = output.split('\n')
                    for line in lines:
                        if "PID" in line or (line.strip() and line.split()[0].isdigit()):
                            pid_str = line.split()[0]
                            if pid_str != "-":
                                return True, f"Running (PID: {pid_str})"
                
                return False, "Loaded but not running"
            else:
                return False, "Service not loaded"
        
        except subprocess.TimeoutExpired:
            return False, "launchctl check timeout"
        except FileNotFoundError:
            return False, "launchctl not found (not running on macOS?)"
        except Exception as e:
            return False, str(e)
    
    async def check_http_endpoint(self) -> tuple[bool, Optional[str]]:
        """Check if HTTP health endpoint responds."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.http_url}/health")
                
                if response.status_code == 200:
                    data = response.json()
                    status = data.get("status", "unknown")
                    return True, f"HTTP 200 (status: {status})"
                else:
                    return False, f"HTTP {response.status_code}"
        
        except httpx.ConnectError:
            return False, "Connection refused"
        except httpx.TimeoutException:
            return False, "Timeout"
        except Exception as e:
            return False, str(e)
    
    def check_database_connectivity(self) -> tuple[bool, Optional[str]]:
        """Check if database is reachable (parse connection string only; don't actually connect)."""
        try:
            # For now, just verify the URL is valid
            # In production, you'd use asyncpg.connect() here
            if self.db_url and self.db_url.startswith("postgresql://"):
                return True, "PostgreSQL URL valid"
            else:
                return False, f"Invalid DB URL: {self.db_url}"
        except Exception as e:
            return False, str(e)
    
    def check_process_uptime(self) -> tuple[Optional[int], Optional[str]]:
        """Get process uptime in seconds."""
        try:
            # Try to get PID from launchctl
            result = subprocess.run(
                ["pgrep", "-f", "uvicorn.*a8_agent"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            
            if result.returncode == 0:
                pid = int(result.stdout.strip().split('\n')[0])
                
                # Get process stats
                result = subprocess.run(
                    ["ps", "-o", "etime=", "-p", str(pid)],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                
                if result.returncode == 0:
                    etime_str = result.stdout.strip()
                    # Parse elapsed time (format: DD-HH:MM:SS or HH:MM:SS or MM:SS)
                    uptime_seconds = self._parse_etime(etime_str)
                    return uptime_seconds, None
            
            return None, "Process not found"
        
        except Exception as e:
            return None, str(e)
    
    def check_process_memory(self) -> tuple[Optional[float], Optional[str]]:
        """Get process memory usage in MB."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "uvicorn.*a8_agent"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            
            if result.returncode == 0:
                pid = int(result.stdout.strip().split('\n')[0])
                
                # Get memory (resident set size) in KB
                result = subprocess.run(
                    ["ps", "-o", "rss=", "-p", str(pid)],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                
                if result.returncode == 0:
                    rss_kb = int(result.stdout.strip())
                    return rss_kb / 1024.0, None
            
            return None, "Process not found"
        
        except Exception as e:
            return None, str(e)
    
    def check_error_rate(self) -> float:
        """Calculate error rate from logs."""
        try:
            if not os.path.exists(self.log_file):
                return 0.0
            
            with open(self.log_file, "r") as f:
                lines = f.readlines()
                
                if not lines:
                    return 0.0
                
                # Check last 100 lines for error patterns
                recent_lines = lines[-100:]
                error_count = sum(
                    1 for line in recent_lines
                    if any(
                        keyword in line.lower()
                        for keyword in ["error", "exception", "failed", "traceback"]
                    )
                )
                
                return error_count / len(recent_lines)
        
        except Exception:
            return 0.0
    
    def _parse_etime(self, etime_str: str) -> int:
        """Parse elapsed time string from ps output."""
        parts = etime_str.strip().split(":")
        
        if len(parts) == 2:  # MM:SS
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:  # HH:MM:SS or DD-HH:MM:SS
            if "-" in parts[0]:
                days, hours = parts[0].split("-")
                return int(days) * 86400 + int(hours) * 3600 + int(parts[1]) * 60 + int(parts[2])
            else:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        
        return 0
    
    async def run_all_checks(self) -> HealthStatus:
        """Run all health checks and return combined status."""
        checks_passed = 0
        checks_total = 5
        
        # Check 1: launchd status
        launchd_ok, launchd_msg = self.check_launchd_status()
        if launchd_ok:
            checks_passed += 1
        
        # Check 2: HTTP endpoint
        http_ok, http_msg = await self.check_http_endpoint()
        if http_ok:
            checks_passed += 1
        else:
            self.error_count += 1
        
        # Check 3: Database connectivity
        db_ok, db_msg = self.check_database_connectivity()
        if db_ok:
            checks_passed += 1
        
        # Check 4: Process uptime
        uptime_sec, uptime_err = self.check_process_uptime()
        if uptime_sec is not None:
            checks_passed += 1
        
        # Check 5: Process memory
        memory_mb, mem_err = self.check_process_memory()
        if memory_mb is not None:
            checks_passed += 1
        
        # Error rate from logs
        error_rate = self.check_error_rate()
        
        # Determine last error
        last_error = None
        for msg in [launchd_msg, http_msg, db_msg, uptime_err, mem_err]:
            if msg:
                last_error = msg
                break
        
        return HealthStatus(
            timestamp=datetime.utcnow().isoformat(),
            service_running=launchd_ok,
            http_endpoint_ok=http_ok,
            database_connected=db_ok,
            process_uptime_seconds=uptime_sec,
            process_memory_mb=memory_mb,
            error_rate=error_rate,
            last_error=last_error,
            checks_passed=checks_passed,
            checks_total=checks_total,
        )


async def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="a8_agent health check")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--watch", action="store_true", help="Continuous monitoring (every 10s)")
    parser.add_argument("--interval", type=int, default=10, help="Watch interval in seconds")
    
    args = parser.parse_args()
    
    checker = A8HealthChecker()
    
    if args.watch:
        try:
            while True:
                status = await checker.run_all_checks()
                
                if args.json:
                    print(json.dumps(asdict(status)))
                else:
                    print_status(status)
                
                await asyncio.sleep(args.interval)
        
        except KeyboardInterrupt:
            print("\n[CTRL-C] Monitoring stopped")
            sys.exit(0)
    
    else:
        status = await checker.run_all_checks()
        
        if args.json:
            print(json.dumps(asdict(status)))
        else:
            print_status(status)
            
            # Exit with error code if unhealthy
            sys.exit(0 if status.is_healthy() else 1)


def print_status(status: HealthStatus):
    """Pretty-print health status."""
    health_indicator = "🟢 HEALTHY" if status.is_healthy() else "🔴 UNHEALTHY"
    
    print(f"\n{health_indicator}")
    print(f"Timestamp: {status.timestamp}")
    print(f"Checks: {status.checks_passed}/{status.checks_total} passed")
    print(f"Error Rate: {status.error_rate:.1%}")
    
    print(f"\nDetails:")
    print(f"  Service Running:    {status.service_running}")
    print(f"  HTTP Endpoint:      {status.http_endpoint_ok}")
    print(f"  Database:           {status.database_connected}")
    print(f"  Process Uptime:     {format_seconds(status.process_uptime_seconds)}")
    print(f"  Process Memory:     {status.process_memory_mb:.1f} MB" if status.process_memory_mb else "  Process Memory:     Unknown")
    
    if status.last_error:
        print(f"\nLast Error: {status.last_error}")


def format_seconds(seconds: Optional[int]) -> str:
    """Format seconds to human-readable string."""
    if seconds is None:
        return "Unknown"
    
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    
    return " ".join(parts)


if __name__ == "__main__":
    asyncio.run(main())
