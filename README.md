# a8_agent

Automated draft generation for cadence enrollments. When contacts enroll in marketing cadences, a8_agent automatically generates personalized email/SMS drafts using templates and AI.

## Quick Start

### Clone & Install

```bash
git clone https://github.com/hjamal7-bit/a8_agent.git
cd a8_agent
pip install -e .
```

### Configure

1. Set your database URL:
```bash
export A8_DATABASE_URL="postgresql://user:password@localhost/a8"
```

2. Set your OpenRouter API key (for draft generation):
```bash
export OPENROUTER_API_KEY="your-key-here"
```

### Start the Service

Development mode (with live reload):
```bash
python -m a8_agent.cli run
```

Production mode (via launchd on macOS):
```bash
# Set up the plist
a8_cadence setup

# Start/stop
launchctl load ~/Library/LaunchAgents/com.a8.agent.plist
launchctl unload ~/Library/LaunchAgents/com.a8.agent.plist
```

### Test It

```bash
# Run integration tests
pytest tests/ -v

# Check health
python monitoring/health_check.py

# Monitor continuously
python monitoring/health_check.py --watch
```

## Architecture

```
Database (PostgreSQL)
    │
    ├─ cadence_instances (on INSERT)
    │   └─ NOTIFY cadence_enroll
    │
    └─ cadence_templates
        └─ cadence_touches (sequence, channel, guidance)

           ↓

a8_agent (FastAPI on port 8788)
    │
    ├─ LISTEN cadence_enroll
    │   └─ generate_for_enrollment(instance_id)
    │       └─ Create drafts in DB
    │
    ├─ POST /cadence/{id}/generate-on-enroll
    │   └─ Manual trigger for regeneration
    │
    ├─ GET /metrics/json
    ├─ GET /metrics/prometheus
    └─ GET /health

           ↓

Drafts Table
    ├─ cadence_instance_id
    ├─ cadence_touch_id
    ├─ contact_id
    ├─ channel (email, sms)
    ├─ subject, body
    ├─ hook, guidance, cta
    └─ status (pending_approval, approved, sent, archived)
```

## Features

- **Event-driven**: Auto-generates drafts when enrollments happen (via LISTEN/NOTIFY)
- **Idempotent**: Won't duplicate drafts for the same touch
- **Metrics**: Prometheus-compatible metrics for monitoring (latency, error rates, throughput)
- **Health checks**: CLI tool to verify service health
- **Batch regeneration**: Manually regenerate drafts for multiple instances
- **Error handling**: Graceful failures with error recording and metrics

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `A8_DATABASE_URL` | Yes | | PostgreSQL connection string |
| `OPENROUTER_API_KEY` | No | | API key for OpenRouter (if using AI draft generation) |
| `A8_PORT` | No | 8788 | HTTP server port |
| `A8_LOG_LEVEL` | No | info | Logging level (debug, info, warning, error) |

### Database Setup

The service expects these tables:

```sql
-- Cadence templates
CREATE TABLE cadence_templates (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL
);

-- Cadence touches (individual steps in the sequence)
CREATE TABLE cadence_touches (
  id UUID PRIMARY KEY,
  cadence_template_id UUID NOT NULL REFERENCES cadence_templates(id),
  sequence_number INT NOT NULL,
  channel TEXT NOT NULL, -- 'email', 'sms', etc
  hook TEXT,              -- subject for email
  guidance TEXT,          -- body content guidance
  cta TEXT,               -- call-to-action
  expected_outcome TEXT,  -- what we expect the contact to do
  tone_guidance TEXT,
  suggested_length_words INT
);

-- Cadence instances (contact enrollments)
CREATE TABLE cadence_instances (
  id UUID PRIMARY KEY,
  cadence_template_id UUID NOT NULL REFERENCES cadence_templates(id),
  contact_id UUID NOT NULL,
  status TEXT DEFAULT 'active'
);

-- Generated drafts
CREATE TABLE drafts (
  id UUID PRIMARY KEY,
  cadence_instance_id UUID NOT NULL REFERENCES cadence_instances(id),
  cadence_touch_id UUID NOT NULL REFERENCES cadence_touches(id),
  contact_id UUID NOT NULL,
  channel TEXT NOT NULL,
  subject TEXT,
  body TEXT,
  hook TEXT,
  guidance TEXT,
  cta TEXT,
  expected_outcome TEXT,
  sequence_number INT,
  is_cadence_draft BOOLEAN DEFAULT FALSE,
  status TEXT DEFAULT 'pending_approval',
  created_from TEXT,
  created_at TIMESTAMP NOT NULL
);

-- Trigger: Auto-generate drafts on enrollment
CREATE FUNCTION notify_cadence_enroll()
RETURNS TRIGGER AS $$
BEGIN
  PERFORM pg_notify('cadence_enroll', NEW.id::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER cadence_enroll_trigger
AFTER INSERT ON cadence_instances
FOR EACH ROW
EXECUTE FUNCTION notify_cadence_enroll();
```

## Monitoring & Metrics

### Health Checks

Check service health:
```bash
python monitoring/health_check.py
```

Output:
```
🟢 HEALTHY
Timestamp: 2026-05-06T23:09:19.694765
Checks: 5/5 passed
Error Rate: 0.0%

Details:
  Service Running:    True
  HTTP Endpoint:      True
  Database:           True
  Process Uptime:     45m 12s
  Process Memory:     8.2 MB
```

### Prometheus Integration

Set up Prometheus to scrape metrics:

1. Follow [PROMETHEUS_SETUP.md](./PROMETHEUS_SETUP.md)
2. Prometheus will scrape `/metrics/prometheus` every 15 seconds
3. Alert rules are pre-configured in `config/alerts.yml`

Metrics available:
- `drafts_generated_total`: Total drafts created
- `drafts_failed_total`: Total generation failures
- `draft_generation_latency_ms`: Generation time (histogram with p50, p95, p99)
- `cadence_enrollments_total`: Total enrollments processed
- `crm_api_calls_total`: Total CRM API interactions
- `up`: Service availability (0=down, 1=up)

### Alerts

Prometheus will fire alerts for:
- Service down (> 1 minute)
- High error rate (> 5% for 5 minutes)
- High latency (p95 > 2 seconds)
- Database errors

See [PROMETHEUS_SETUP.md](./PROMETHEUS_SETUP.md) for alertmanager integration.

## API Endpoints

### GET /health
Service health check.

```bash
curl http://localhost:8788/health
```

### GET /metrics/json
Metrics in JSON format.

```bash
curl http://localhost:8788/metrics/json
```

### GET /metrics/prometheus
Metrics in Prometheus format (for scraping).

```bash
curl http://localhost:8788/metrics/prometheus
```

### POST /cadence/{cadence_instance_id}/generate-on-enroll
Manually trigger draft generation for an enrollment.

```bash
curl -X POST http://localhost:8788/cadence/inst-123/generate-on-enroll
```

Response:
```json
{
  "generated": ["draft-1", "draft-2"],
  "skipped": 0,
  "latency_ms": 245,
  "error": null
}
```

### POST /cadence/regenerate
Regenerate drafts for multiple instances (batch operation).

```bash
curl -X POST http://localhost:8788/cadence/regenerate \
  -H "Content-Type: application/json" \
  -d '{"instance_ids": ["inst-123", "inst-456"]}'
```

## Troubleshooting

### Service won't start

Check logs:
```bash
tail -f /tmp/a8_agent.log
```

Verify database is accessible:
```bash
psql $A8_DATABASE_URL -c "SELECT 1"
```

Verify the service isn't already running:
```bash
lsof -i :8788
```

### High error rate

1. Check database:
```bash
python monitoring/health_check.py
```

2. Review logs for specific errors:
```bash
python -m a8_agent.cli logs --tail 100 --level error
```

3. Check metrics:
```bash
curl http://localhost:8788/metrics/json | jq '.drafts_failed_total'
```

### Drafts not generating

1. Verify the database trigger is set up:
```sql
SELECT * FROM pg_trigger WHERE tgname = 'cadence_enroll_trigger';
```

2. Check if listener is connected:
```bash
curl http://localhost:8788/health | jq '.listener_status'
```

3. Try manual trigger:
```bash
curl -X POST http://localhost:8788/cadence/{instance_id}/generate-on-enroll
```

See [RUNBOOK.md](./RUNBOOK.md) for more operational procedures.

## Development

### Project Structure

```
a8_agent/
├── a8_agent/
│   ├── __init__.py
│   ├── cadence_draft_handler.py    # Core logic
│   ├── metrics.py                   # Metrics collection
│   ├── cli.py                       # CLI interface
│   └── web/
│       ├── app.py                   # FastAPI app
│       └── routes.py                # HTTP endpoints
├── monitoring/
│   ├── health_check.py              # Health check tool
│   └── __init__.py
├── tests/
│   ├── test_cadence_trigger.py      # Integration tests
│   └── conftest.py                  # Test fixtures
├── config/
│   ├── prometheus.yml               # Prometheus config
│   └── alerts.yml                   # Alert rules
├── RUNBOOK.md                       # Operational runbook
├── PROMETHEUS_SETUP.md              # Monitoring setup
└── setup.py
```

### Running Tests

```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=a8_agent

# Specific test
pytest tests/test_cadence_trigger.py::test_enrollment_generates_drafts -v
```

### Code Style

- Python 3.10+
- Type hints required
- PEP 8 formatting
- Docstrings for all functions/classes

### Dependencies

- `fastapi`: HTTP server
- `asyncpg`: PostgreSQL driver
- `prometheus-client`: Metrics export
- `pytest`, `pytest-asyncio`: Testing

Development dependencies:
```bash
pip install -e '.[dev]'
```

## Deployment

### Systemd (Linux)

Create `/etc/systemd/system/a8-agent.service`:
```ini
[Unit]
Description=a8_agent cadence draft generation
After=postgresql.service

[Service]
Type=simple
User=app
WorkingDirectory=/opt/a8_agent
ExecStart=/opt/a8_agent/venv/bin/python -m a8_agent.cli run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable a8-agent
sudo systemctl start a8-agent
```

### Docker

A Dockerfile is available in the repo. Build and run:
```bash
docker build -t a8_agent .
docker run -d \
  -e A8_DATABASE_URL="postgresql://..." \
  -e OPENROUTER_API_KEY="..." \
  -p 8788:8788 \
  a8_agent
```

## Links

- **GitHub**: https://github.com/hjamal7-bit/a8_agent
- **Issue Tracker**: https://github.com/hjamal7-bit/a8_agent/issues
- **Runbook**: [RUNBOOK.md](./RUNBOOK.md)
- **Monitoring**: [PROMETHEUS_SETUP.md](./PROMETHEUS_SETUP.md)
- **CRM Integration**: [CRM_INTEGRATION.md](./CRM_INTEGRATION.md)

## License

Internal use only.
