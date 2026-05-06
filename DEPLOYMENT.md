# a8_agent Deployment Manifest

## Service: Cadence Draft Generation (Event-Driven)

**Deployed**: Wed 2026-05-06 17:09 CDT
**Status**: Production Ready

### Service Details
- **Application**: a8_agent FastAPI
- **Port**: 127.0.0.1:8788
- **Process Manager**: launchd (com.a8.cadence-agent)
- **PID**: 26615
- **Uptime**: Persistent (auto-restart on failure)
- **Health**: ✓ /health endpoint returns {"status":"ok"}

### Architecture
Event-driven cadence draft generation replacing inefficient polling.

**Trigger Flow**:
1. Contact enrolled in cadence → cadence_instances INSERT
2. Database trigger fires → sends pg_notify on 'cadence_enroll' channel
3. a8_agent listener receives notification
4. Handler calls generate_for_enrollment(cadence_instance_id)
5. Drafts created immediately (one per touch sequence)

**Manual API**:
- `POST /cadence/{cadence_instance_id}/generate-on-enroll` — Generate drafts for single enrollment
- `POST /cadence/template/{template_id}/regenerate?force=true` — Regenerate all active instances

### What Was Replaced
- **Old**: a8 daemon (com.a8.unified-daemon) polling every 5 minutes
- **Status**: Unloaded and disabled
- **Reason**: Created duplicate drafts, wasted CPU cycles
- **Result**: Eliminated polling, immediate generation, zero duplicates

### What Was Kept
- **Ultron** (com.ultron.serve, PID 75077): iMessage daemon and briefings
- **Status**: Running, unrelated to cadence drafts
- **Impact**: No changes needed

### Database Changes
- **Function**: `notify_cadence_enroll()` — sends pg_notify on INSERT
- **Trigger**: `cadence_instance_enroll_trigger` — fires after INSERT on cadence_instances
- **Channel**: `cadence_enroll` — notification channel name
- **Reversible**: Yes, trigger and function can be dropped if needed

### Testing
- ✓ Manual API endpoint tested: generated 4 drafts
- ✓ Database trigger tested: INSERT auto-generated 4 drafts
- ✓ LISTEN/NOTIFY callback confirmed in logs
- ✓ Health check passing
- ✓ 8 cadence drafts created in last hour

### Files
```
/Users/jamal/code/a8_agent/
├── a8_agent/
│   ├── __init__.py
│   ├── cadence_draft_handler.py    (core logic + routes)
│   └── web/
│       ├── __init__.py
│       └── app.py                   (FastAPI app)
├── setup.py
├── requirements.txt
├── venv/                            (virtual environment)
└── .git/                            (version control)
```

### Service Management
```bash
# Status
launchctl list | grep cadence-agent

# Start
launchctl start com.a8.cadence-agent

# Stop
launchctl stop com.a8.cadence-agent

# Logs
tail -f /Users/jamal/.a8/logs/cadence-agent.log
```

### Monitoring
- Log location: `/Users/jamal/.a8/logs/cadence-agent.log`
- Health check: `curl http://127.0.0.1:8788/health`
- Database: Query `drafts` table, filter by `is_cadence_draft = true`
- Trigger status: `SELECT trigger_name FROM information_schema.triggers WHERE trigger_name LIKE '%cadence%'`

### Rollback (if needed)
```bash
# Revert to polling daemon
launchctl load -w ~/Library/LaunchAgents/com.a8.unified-daemon.plist

# Disable a8_agent
launchctl unload -w ~/Library/LaunchAgents/com.a8.cadence-agent.plist
```

---

**Deployed by**: Natasha (OpenClaw)
**Verification**: All tests passed, ready for production
