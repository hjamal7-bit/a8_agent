# CRM API Integration - Draft Endpoints Alignment

## Overview
a8_agent generates cadence drafts and stores them in the shared `drafts` table. The CRM API at `http://localhost:8787/crm/tables/drafts` exposes this table via REST.

## Data Flow

```
Contact enrolled in cadence
  ↓
cadence_instances INSERT
  ↓
Database trigger fires: notify_cadence_enroll()
  ↓
PostgreSQL LISTEN/NOTIFY sends 'cadence_enroll' event
  ↓
a8_agent listener receives notification
  ↓
CadenceDraftGenerator.generate_for_enrollment(cadence_instance_id)
  ↓
INSERT drafts with:
  - cadence_instance_id (links to cadence)
  - cadence_touch_id (links to sequence step)
  - is_cadence_draft = true
  - body, subject (generated from template)
  - status = 'pending_approval'
  ↓
Drafts available in:
  - PostgreSQL: drafts table
  - a8_agent API: /cadence endpoints
  - CRM API: /crm/tables/drafts (subject to CRM filtering)
```

## Database Schema

All cadence drafts are stored in the shared `drafts` table:

```sql
CREATE TABLE drafts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cadence_instance_id uuid NOT NULL,        -- Links to cadence_instances
  cadence_touch_id uuid,                    -- Links to cadence_touches (sequence step)
  cadence_scheduled_at timestamp,           -- When this draft is scheduled to send
  is_cadence_draft boolean DEFAULT false,   -- TRUE for cadence-generated drafts
  
  -- Contact and content
  contact_id uuid,
  opco_id uuid,
  channel text NOT NULL,                    -- 'email', 'sms', etc
  subject text,
  body text NOT NULL,
  
  -- Generation metadata
  generation_model text,                    -- 'claude-sonnet-4-6', etc
  created_at timestamp DEFAULT now(),
  updated_at timestamp DEFAULT now(),
  
  -- Approval and state
  status text DEFAULT 'pending_approval',   -- pending_approval, approved, sent, failed
  approved_at timestamp,
  approved_by uuid,
  
  -- Outcome tracking
  reply_received_at timestamp,
  reply_body text,
  marked_as_bounced boolean DEFAULT false,
  
  ... (other fields)
};
```

## API Endpoints

### a8_agent HTTP API
Base URL: `http://127.0.0.1:8788`

**Generate drafts for single enrollment:**
```
POST /cadence/{cadence_instance_id}/generate-on-enroll
Query params:
  - force: bool (default false) - regenerate even if drafts exist
```

Response:
```json
{
  "cadence_instance_id": "uuid",
  "generated_count": 4,
  "drafts": [
    {
      "id": "uuid",
      "sequence_number": 1,
      "subject": "...",
      "created_at": "2026-05-06T14:28:51.463075-05:00"
    }
  ]
}
```

**Regenerate all drafts for a template:**
```
POST /cadence/template/{template_id}/regenerate
Query params:
  - force: bool (default false) - regenerate even if drafts exist
```

Response:
```json
{
  "template_id": "uuid",
  "instances_processed": 4,
  "generated_count": 16,
  "message": "Regenerated drafts for 4 active instances"
}
```

### CRM API
Base URL: `http://localhost:8787/crm`

**Query drafts:**
```
GET /tables/drafts?limit=50
Header:
  Authorization: Bearer {token}
```

Response:
```json
{
  "data": [
    {
      "id": "uuid",
      "cadence_instance_id": "uuid",
      "is_cadence_draft": true,
      "contact_id": "uuid",
      "subject": "...",
      "body": "...",
      "status": "pending_approval",
      "created_at": "2026-05-06T14:28:51.463075-05:00"
    }
  ],
  "count": 30
}
```

Note: The CRM API may apply additional filtering (e.g., visibility checks, permission scopes). If all drafts don't appear, check the CRM's table configuration.

## CLI Command

```bash
# Check a8_agent health
a8_cadence status

# Regenerate drafts for a specific cadence instance
a8_cadence regenerate <cadence_instance_id> --instance

# Regenerate all drafts for a template
a8_cadence regenerate <template_id>

# Force regeneration even if drafts exist
a8_cadence regenerate <template_id> --force

# Tail logs
a8_cadence logs
```

## Testing Alignment

### Verify a8_agent generated the drafts:
```bash
# Check via HTTP
curl http://127.0.0.1:8788/health

# Check via CLI
a8_cadence status

# Check logs
a8_cadence logs
```

### Verify CRM sees the drafts:
```bash
# Get CRM token
cat ~/.a8/openclaw_token

# Query CRM API
curl "http://localhost:8787/crm/tables/drafts?limit=10" \
  -H "Authorization: Bearer $(cat ~/.a8/openclaw_token)"
```

### Verify database:
```bash
psql -d a8 -c "
  SELECT 
    COUNT(*) as draft_count,
    COUNT(DISTINCT cadence_instance_id) as instances,
    MAX(created_at) as latest
  FROM drafts 
  WHERE is_cadence_draft = true;
"
```

## Known Behaviors

### Duplicate Drafts
Before a8_agent, the a8 daemon polled every 5 minutes and created duplicates. This is now eliminated. Each enrollment generates exactly one draft sequence (one per touch in the cadence).

### Immediate Generation
Drafts are created immediately upon enrollment via database trigger, not on a schedule. This eliminates delays and ensures consistency.

### Manual Control
Use `a8_cadence regenerate` or the HTTP endpoints to manually regenerate drafts for a template or instance. This gives full control without automatic polling.

### CRM Filtering
If drafts don't appear in the CRM API, check:
1. Are they in the database? Query `drafts WHERE is_cadence_draft = true`
2. Is the CRM filtering them? Check CRM table config for visibility rules
3. Is the token valid? Verify `~/.a8/openclaw_token`
4. Is the service running? Check `a8_cadence status`

## Troubleshooting

### a8_agent not responding
```bash
# Check if service is running
launchctl list | grep cadence-agent

# Restart the service
launchctl stop com.a8.cadence-agent
launchctl start com.a8.cadence-agent

# Check logs
tail -f ~/.a8/logs/cadence-agent.log
```

### Database trigger not firing
```bash
# Verify trigger exists
psql -d a8 -c "
  SELECT trigger_name FROM information_schema.triggers
  WHERE trigger_name = 'cadence_instance_enroll_trigger';
"

# Check if pg_notify extension is installed
psql -d a8 -c "CREATE EXTENSION IF NOT EXISTS plpgsql;"

# Check listener logs
a8_cadence logs | grep "notify\|listener"
```

### Drafts not appearing in CRM
1. Verify they exist in the database
2. Check CRM token is valid
3. Check CRM API response for filtering messages
4. Contact CRM maintainer if API is filtering unexpectedly

## Version
- a8_agent: 0.1.0
- Database: PostgreSQL (a8 schema)
- CRM: Alpha 8 Personal CRM
- Last updated: Wed 2026-05-06 17:17 CDT
