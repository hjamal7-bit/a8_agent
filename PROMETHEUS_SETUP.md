# Prometheus Monitoring Setup

This guide explains how to run Prometheus locally to scrape metrics from a8_agent.

## Option 1: Docker (Recommended)

The easiest way to run Prometheus locally.

### Requirements
- Docker installed

### Steps

1. Start Prometheus with the a8_agent config:
```bash
docker run -d \
  --name prometheus \
  -p 9090:9090 \
  -v /Users/jamal/code/a8_agent/config/prometheus.yml:/etc/prometheus/prometheus.yml \
  -v /Users/jamal/code/a8_agent/config/alerts.yml:/etc/prometheus/alerts.yml \
  prom/prometheus:latest \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus
```

2. Verify it's running:
```bash
curl http://localhost:9090/api/v1/query?query=up
```

3. Open the UI in your browser:
```
http://localhost:9090
```

4. Query a8_agent metrics (in the UI search bar):
```
drafts_generated_total
draft_generation_latency_ms_bucket
cadence_enrollments_total
```

5. Stop it:
```bash
docker stop prometheus && docker rm prometheus
```

## Option 2: Homebrew (macOS)

If you prefer to run Prometheus on the host.

### Requirements
- Homebrew

### Steps

1. Install Prometheus:
```bash
brew install prometheus
```

2. Check installation:
```bash
prometheus --version
```

3. Start Prometheus with the a8_agent config:
```bash
prometheus \
  --config.file=/Users/jamal/code/a8_agent/config/prometheus.yml \
  --storage.tsdb.path=/tmp/prometheus-tsdb
```

4. Open the UI:
```
http://localhost:9090
```

5. Stop it with Ctrl+C.

## Configuration

The included `config/prometheus.yml` is pre-configured to:
- Scrape a8_agent metrics from `http://localhost:8788/metrics/prometheus`
- Scrape every 15 seconds
- Load alerting rules from `config/alerts.yml`

## Alert Rules

Prometheus will evaluate these alerts every 1 minute:

1. **A8AgentServiceDown**: Fires if a8_agent doesn't respond for 1 minute (severity: critical)
2. **A8AgentHighErrorRate**: Fires if error rate exceeds 5% for 5 minutes (severity: warning)
3. **A8AgentHighLatency**: Fires if p95 draft generation latency exceeds 2 seconds (severity: warning)
4. **A8AgentDatabaseError**: Fires if database errors are detected (severity: warning)

### Alertmanager Integration (Optional)

To send alerts somewhere (email, Slack, PagerDuty), integrate with Alertmanager:

1. Install Alertmanager:
```bash
brew install alertmanager
```

2. Edit `config/alertmanager.yml` with your notification channels (see [alertmanager docs](https://prometheus.io/docs/alerting/alertmanager/config/))

3. Update `prometheus.yml` to point to alertmanager:
```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets: ['localhost:9093']
```

4. Start Alertmanager:
```bash
alertmanager --config.file=/path/to/alertmanager.yml
```

## Metrics Available

All metrics are Prometheus-compatible and exported at `/metrics/prometheus`:

- `drafts_generated_total`: Total number of drafts generated (counter)
- `drafts_failed_total`: Total number of failed draft generations (counter)
- `draft_generation_latency_ms`: Draft generation latency in milliseconds (histogram)
- `cadence_enrollments_total`: Total enrollments processed (counter)
- `crm_api_calls_total`: Total CRM API calls (counter)
- `up`: Scrape indicator (1 = up, 0 = down) (gauge)

## Querying Examples

In the Prometheus web UI, try these queries:

```promql
# Recent error rate (last 5m)
rate(drafts_failed_total[5m]) / (rate(drafts_generated_total[5m]) + rate(drafts_failed_total[5m]))

# 95th percentile latency
histogram_quantile(0.95, rate(draft_generation_latency_ms_bucket[5m]))

# Drafts per minute (last hour)
rate(drafts_generated_total[1h])

# Is a8_agent healthy?
up{job="a8-agent"}
```

## Troubleshooting

### Prometheus can't scrape a8_agent

1. Check a8_agent is running on port 8788:
```bash
lsof -i :8788
```

2. Check the metrics endpoint is accessible:
```bash
curl http://localhost:8788/metrics/prometheus
```

3. Check Prometheus logs (in Docker):
```bash
docker logs prometheus
```

### Alerts not firing

1. Verify Prometheus has data:
```
http://localhost:9090/targets
```

2. Check alert rules are loaded:
```
http://localhost:9090/alerts
```

3. Manually query the metric:
```
http://localhost:9090/graph?expr=drafts_failed_total
```

### High disk usage

Prometheus stores time-series data in `/tmp/prometheus-tsdb`. To clean it up:
```bash
rm -rf /tmp/prometheus-tsdb
# Restart Prometheus
```

## Further Reading

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Alertmanager Configuration](https://prometheus.io/docs/alerting/alertmanager/config/)
- [PromQL Query Language](https://prometheus.io/docs/prometheus/latest/querying/basics/)
