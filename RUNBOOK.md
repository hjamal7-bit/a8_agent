# a8_agent Operational Runbook

Complete guide for running, monitoring, and troubleshooting the a8_agent service.

**Service Name:** com.jamal.a8-cadence-agent  
**Port:** 8788  
**Database:** PostgreSQL (configured via A8_DATABASE_URL)  
**Logs:** ~/.a8/logs/cadence-agent.log

---

## Table of Contents

1. [Startup](#startup)
2. [Shutdown](#shutdown)
3. [Health Checks](#health-checks)
4. [Common Failure Modes](#common-failure-modes)
5. [Log Locations](#log-locations)
6. [Restart Procedures](#restart-procedures)
7. [Emergency Contact](#emergency-contact)
8. [Metrics & Monitoring](#metrics--monitoring)

---

## Startup

### Manual Startup (Development)

```bash
# Activate virtual environment
source /Users/jamal/code/a8_agent/venv/bin/activate

# Set environment variables
export A8_DATABASE_URL="postgresql://user:pass@localhost/a8_crm"
export A8_AGENT_URL="http://127.0.0.1:8788"

# Start the service
cd /Users/jamal/code/a8_agent
python -m uvicorn a8_agent.web.app:app --host 127.0.0.1 --port 8788 --reload
```

### Production Startup (via launchd)

The service is registered as a macOS launch agent. To start it:

```bash
# Load the service
launchctl load ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist

# Verify it's running
launchctl list com.jamal.a8-cadence-agent
```

If the plist does not exist yet, create it:

```bash
mkdir -p ~/Library/LaunchAgents

cat > ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jamal.a8-cadence-agent</string>
    <key>Program</key>
    <string>/Users/jamal/code/a8_agent/venv/bin/python</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/jamal/code/a8_agent/venv/bin/python</string>
        <string>-m</string>
        <string>uvicorn</string>
        <string>a8_agent.web.app:app</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>8788</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/jamal/code/a8_agent</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>A8_DATABASE_URL</key>
        <string>postgresql://user:pass@localhost/a8_crm</string>
        <key>A8_AGENT_URL</key>
        <string>http://127.0.0.1:8788</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/jamal/.a8/logs/cadence-agent.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/jamal/.a8/logs/cadence-agent.log</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StartInterval</key>
    <integer>60</integer>
</dict>
</plist>
EOF

# Load it
launchctl load ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist
```

---

## Shutdown

### Graceful Shutdown

```bash
# Stop via launchctl
launchctl unload ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist

# Or kill the process gracefully
kill -TERM $(pgrep -f "uvicorn.*a8_agent")

# Wait 5-10 seconds for graceful shutdown
sleep 5

# Verify it stopped
ps aux | grep "uvicorn.*a8_agent" | grep -v grep || echo "Stopped"
```

### Forced Shutdown (Last Resort)

```bash
kill -9 $(pgrep -f "uvicorn.*a8_agent")
```

---

## Health Checks

### Quick Health Status

```bash
# Check if service is responding
curl http://127.0.0.1:8788/health

# Expected response:
# {"status": "ok", "service": "a8_agent"}
```

### Comprehensive Health Check

```bash
# Run the health check script (shows launchd status, uptime, memory, etc.)
python /Users/jamal/code/a8_agent/monitoring/health_check.py

# Watch health continuously (every 10 seconds)
python /Users/jamal/code/a8_agent/monitoring/health_check.py --watch

# Get health as JSON
python /Users/jamal/code/a8_agent/monitoring/health_check.py --json
```

### Metrics Endpoints

```bash
# JSON metrics snapshot
curl http://127.0.0.1:8788/metrics/json | jq

# Prometheus format metrics
curl http://127.0.0.1:8788/metrics/prometheus

# Quick health from metrics
curl http://127.0.0.1:8788/metrics/health | jq
```

### Database Connectivity

```bash
# Test database connection directly
psql $A8_DATABASE_URL -c "SELECT 1"

# If that fails, check connection string
echo $A8_DATABASE_URL
```

### Listener Status

```bash
# Check if LISTEN/NOTIFY is working
psql $A8_DATABASE_URL << 'EOF'
LISTEN cadence_enroll;
-- Wait for notifications or CTRL-C
EOF
```

---

## Common Failure Modes

### 1. Service Won't Start

**Symptoms:** launchctl status shows no PID, or service crashes on startup

**Check:**
- Is the Python environment valid?
  ```bash
  source /Users/jamal/code/a8_agent/venv/bin/activate
  python --version
  ```

- Are dependencies installed?
  ```bash
  pip list | grep -E "fastapi|asyncpg|uvicorn"
  ```

- Is the port 8788 already in use?
  ```bash
  lsof -i :8788
  # If something is there, kill it or use a different port
  ```

- Check recent logs for errors:
  ```bash
  tail -50 ~/.a8/logs/cadence-agent.log
  ```

**Fix:**
```bash
# Reinstall dependencies
cd /Users/jamal/code/a8_agent
pip install -e .

# Try starting manually to see the error
python -m uvicorn a8_agent.web.app:app --host 127.0.0.1 --port 8788
```

### 2. Database Connection Failed

**Symptoms:** Requests fail with connection errors, logs show "psycopg2" or "asyncpg" errors

**Check:**
- Is PostgreSQL running?
  ```bash
  pg_isready -h localhost
  ```

- Is the connection string valid?
  ```bash
  echo $A8_DATABASE_URL
  # Should look like: postgresql://user:password@host:port/dbname
  ```

- Can you connect manually?
  ```bash
  psql $A8_DATABASE_URL -c "SELECT 1"
  ```

**Fix:**
```bash
# Verify/update the environment variable
export A8_DATABASE_URL="postgresql://user:password@localhost:5432/a8_crm"

# Reload the service
launchctl unload ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist
launchctl load ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist

# Verify connectivity
curl http://127.0.0.1:8788/health
```

### 3. High Error Rate or Crashes

**Symptoms:** /metrics/json shows error_rate > 0.1, or service keeps crashing

**Check:**
- Look at recent error logs
  ```bash
  grep -i "error\|exception\|traceback" ~/.a8/logs/cadence-agent.log | tail -20
  ```

- Check if database query is hitting a constraint
  ```bash
  psql $A8_DATABASE_URL << 'EOF'
  SELECT * FROM pg_stat_statements WHERE query ILIKE '%draft%' ORDER BY calls DESC LIMIT 5;
  EOF
  ```

- Check memory usage
  ```bash
  python /Users/jamal/code/a8_agent/monitoring/health_check.py | grep Memory
  ```

**Fix:**
```bash
# If memory is high, restart the service
launchctl unload ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist
sleep 2
launchctl load ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist

# If specific query is slow, add an index
psql $A8_DATABASE_URL << 'EOF'
CREATE INDEX IF NOT EXISTS idx_drafts_cadence_instance_touch 
  ON drafts(cadence_instance_id, cadence_touch_id);
EOF
```

### 4. Listener Not Receiving Notifications

**Symptoms:** Drafts aren't auto-generating on enrollment, or manual endpoint works but trigger doesn't

**Check:**
- Is the database trigger still there?
  ```bash
  psql $A8_DATABASE_URL << 'EOF'
  SELECT * FROM information_schema.triggers WHERE trigger_schema='public' AND trigger_name ILIKE '%cadence%';
  EOF
  ```

- Is the trigger calling NOTIFY?
  ```bash
  psql $A8_DATABASE_URL << 'EOF'
  SELECT pg_get_triggerdef(oid) FROM pg_trigger WHERE tgname = 'cadence_enroll_notify';
  EOF
  ```

- Are there any trigger errors?
  ```bash
  tail -100 ~/.a8/logs/cadence-agent.log | grep -i "listener\|notify"
  ```

**Fix:**
```bash
# Recreate the trigger
psql $A8_DATABASE_URL << 'EOF'
DROP TRIGGER IF EXISTS cadence_enroll_notify ON cadence_instances;

CREATE TRIGGER cadence_enroll_notify
  AFTER INSERT ON cadence_instances
  FOR EACH ROW
  EXECUTE FUNCTION pg_notify('cadence_enroll', NEW.id::text);
EOF

# Restart the service
launchctl unload ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist
launchctl load ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist
```

### 5. Port 8788 Already in Use

**Symptoms:** "Address already in use" in logs, curl to health endpoint fails

**Check:**
```bash
lsof -i :8788
```

**Fix:**
```bash
# Option 1: Kill the existing process
kill -9 <PID>

# Option 2: Use a different port (update environment and plist)
export A8_AGENT_URL="http://127.0.0.1:8789"
# Update plist to use port 8789 instead

# Option 3: Check if it's actually a8_agent and restart it cleanly
launchctl unload ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist
sleep 2
launchctl load ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist
```

---

## Log Locations

### Main Service Log

```bash
# Live tail
tail -f ~/.a8/logs/cadence-agent.log

# Last 100 lines
tail -100 ~/.a8/logs/cadence-agent.log

# Search for errors
grep ERROR ~/.a8/logs/cadence-agent.log | tail -20

# Search for specific operation
grep "cadence_enroll\|generate_for_enrollment" ~/.a8/logs/cadence-agent.log
```

### Application Logs

- **Location:** ~/.a8/logs/cadence-agent.log
- **Format:** Text (from uvicorn/FastAPI)
- **Rotation:** None (manual cleanup or use logrotate)

### Database Query Logs

```bash
# Enable PostgreSQL query logging (in postgresql.conf)
# log_statement = 'all'
# log_min_duration_statement = 1000  # Log queries taking > 1 second

# View slow queries
psql $A8_DATABASE_URL << 'EOF'
SELECT * FROM pg_stat_statements WHERE mean_time > 1000 ORDER BY mean_time DESC LIMIT 10;
EOF
```

---

## Restart Procedures

### Cold Restart (Full Shutdown + Startup)

Use when:
- Service is stuck or unresponsive
- Database connection is lost
- After deploying code changes

```bash
# 1. Stop the service
launchctl unload ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist

# 2. Wait for cleanup
sleep 2

# 3. Check nothing is still running
ps aux | grep -i "a8_agent\|cadence" | grep -v grep

# 4. Clear any stale database connections (optional)
psql $A8_DATABASE_URL << 'EOF'
SELECT pg_terminate_backend(pid) FROM pg_stat_activity 
WHERE datname = 'a8_crm' AND pid <> pg_backend_pid();
EOF

# 5. Start the service
launchctl load ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist

# 6. Verify startup
sleep 3
curl http://127.0.0.1:8788/health
```

### Rolling Restart (Minimal Downtime)

Use when:
- Making config changes
- Updating metrics or monitoring

```bash
# 1. Reload the service (kills and restarts)
launchctl unload ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist
launchctl load ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist

# 2. Verify it's up
sleep 2
curl http://127.0.0.1:8788/health
```

### Restart After Crash

a8_agent is configured with `KeepAlive=true` in launchd, so it will auto-restart on crash.

To manually check and restart:

```bash
# Check status
launchctl list com.jamal.a8-cadence-agent

# If it shows a negative PID (stopped), restart it
launchctl unload ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist
launchctl load ~/Library/LaunchAgents/com.jamal.a8-cadence-agent.plist

# Monitor startup
python /Users/jamal/code/a8_agent/monitoring/health_check.py --watch
```

---

## Emergency Contact

**Owner:** JJ Jamal  
**Email:** [configured in system]  
**Escalation:** If service is down for >30 minutes and self-healing fails

---

## Metrics & Monitoring

### Key Metrics to Watch

```bash
# Get full snapshot
curl http://127.0.0.1:8788/metrics/json | jq .
```

**Critical Metrics:**

- **drafts.success_rate**: Should be > 0.95. If < 0.90, investigate errors
- **drafts.latency.p95_ms**: Should be < 1000ms. If > 5000ms, database is slow
- **crm_api.error_rate**: Should be < 0.05. High error rate indicates CRM connectivity issues
- **jobs.active**: Should be 0 when idle, spike on enrollment
- **uptime_seconds**: Watch for unexpected restarts

### Setting Up Prometheus Scraping

If using Prometheus:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'a8_agent'
    static_configs:
      - targets: ['127.0.0.1:8788']
    metrics_path: '/metrics/prometheus'
    scrape_interval: 30s
```

### Setting Up Alerting

Example alert rules (for Prometheus + Alertmanager):

```yaml
groups:
  - name: a8_agent
    rules:
      - alert: A8AgentDown
        expr: up{job="a8_agent"} == 0
        for: 2m
        annotations:
          summary: "a8_agent is down"

      - alert: A8HighErrorRate
        expr: a8_drafts_failed_total / (a8_drafts_generated_total + a8_drafts_failed_total) > 0.1
        for: 5m
        annotations:
          summary: "a8_agent error rate is {{ $value | humanizePercentage }}"

      - alert: A8SlowDraftGeneration
        expr: a8_draft_generation_latency_ms > 5000
        for: 5m
        annotations:
          summary: "Draft generation is slow ({{ $value }}ms)"
```

---

## Troubleshooting Checklist

- [ ] Service is running: `launchctl list com.jamal.a8-cadence-agent`
- [ ] Health endpoint responds: `curl http://127.0.0.1:8788/health`
- [ ] Database is reachable: `psql $A8_DATABASE_URL -c "SELECT 1"`
- [ ] Port 8788 is not in use by another service: `lsof -i :8788`
- [ ] Error rate is acceptable: `curl http://127.0.0.1:8788/metrics/health | jq`
- [ ] Logs show no recent errors: `tail -50 ~/.a8/logs/cadence-agent.log`
- [ ] No stale database connections: `psql $A8_DATABASE_URL -c "SELECT * FROM pg_stat_activity"`
- [ ] Memory usage is reasonable: `python monitoring/health_check.py | grep Memory`

If all checks pass and the service is still having issues, see **Common Failure Modes** above.

---

## References

- a8_agent source: /Users/jamal/code/a8_agent
- CRM integration docs: DEPLOYMENT.md, CRM_INTEGRATION.md
- Health check script: monitoring/health_check.py
- CLI commands: a8_agent/cli.py (run `a8_cadence --help`)
