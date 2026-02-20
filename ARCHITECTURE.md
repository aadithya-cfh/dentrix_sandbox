# System Architecture

## Data Flow Pattern

| Flow | Description |
|------|-------------|
| **WRITE** | App → Postgres → EHR-Connector → Dentrix *(Data stored in Postgres first, then synced to EHR)* |
| **READ** | App reads directly from Postgres *(Daily cron syncs latest EHR data to Postgres)* |

---

```
                            ┌─────────────────┐
                            │     Dentrix     │
                            │       EHR       │
                            └────────┬────────┘
                                     │
                         Write ↑     ↓ Sync
                                     │
                            ┌────────┴────────┐          ┌─────────────┐
                            │  EHR-Connector  │◄─ ─ ─ ─ ─│  Daily Sync │
                            │  (Dentrix API)  │          │  (Cron Job) │
                            │    OAuth 2.0    │          └─────────────┘
                            └────────┬────────┘                 │
                                     │                          │
                                  ┌──┴──┐                       │
                                  │  ↻  │  Sync                 │
                                  └──┬──┘                       │
                                     │                          │
               Write to EHR ↑        │                          │ Daily Sync
                            │        │                          │
                            │        ▼                          │
       ┌────────────────────┴────────────────────┐              │
       │         Appointment-Manager             │    Write     │
       │              (Confido)                  │────────►┌────┴────────┐
       │                CRUD                     │         │  Postgres   │
       │  ●  ●  ●                           ●   │◄────────│  (Supabase) │
       └────────────────────┬────────────────────┘   Read  └─────────────┘
                            │                          Source of Truth
                            │
                            ▼
                    ┌───────────────┐
       ┌─────┐      │               │      ┌─────────┐
       │     │      │ Retell Agents │      │         │
       │ Out │◄────►│   (Voice AI)  │◄────►│ Inbound │
       │bound│      │               │      │         │
       └─────┘      └───────────────┘      └─────────┘
```

---

## Component Details

### Dentrix EHR
- External Electronic Health Record system
- Source of patient and appointment data
- Accessed via OAuth 2.0 API

### EHR-Connector (Dentrix API)
- Handles authentication (OAuth 2.0 client credentials)
- CRUD operations for patients, appointments, providers
- Rate limit handling (429 with Retry-After)

### Appointment-Manager (Confido)
- Core business logic layer
- Manages appointment scheduling
- Coordinates between database and EHR

### Postgres (Supabase)
- **Source of Truth** for the application
- All reads happen directly from here
- All writes go here first, then sync to EHR
- Historical record tracking (SCD Type 2)

### Daily Sync (Cron Job)
- Runs incremental sync from EHR to Postgres
- Uses cursor-based pagination (`lastId`)
- Tracks sync state with timestamps

### Retell Agents (Voice AI)
- Handles inbound and outbound calls
- Patient verification and appointment management
- Powered by Retell AI

---

## Data Operations

| Operation | Flow |
|-----------|------|
| Create Patient | App → Postgres → EHR-Connector → Dentrix |
| Update Appointment | App → Postgres → EHR-Connector → Dentrix |
| Read Patient Info | App ← Postgres |
| Read Appointments | App ← Postgres |
| Sync Latest Data | Dentrix → EHR-Connector → Postgres (Daily) |

---

## Free-Slots Calculation

```
Free-Slots = Availability - Unavailability - Blocked Slots - Appointments
```

## EventType Defaults
- `operatoryIds` - List of operatory IDs
- `duration` - Appointment duration in minutes
- `offsetStart` - Start time offset

---

## API Endpoints

### Read Operations (Sync to Postgres)

| Endpoint | Method | Action | Cadence | Use Case |
|----------|--------|--------|---------|----------|
| `/v1/patients` | GET | Fetch all patients with filters | Daily Cron | Sync patient data to Postgres |
| `/v1/appointments` | GET | Fetch appointments with date range | Daily Cron | Sync appointment data to Postgres |
| `/v1/providers` | GET | Fetch provider list | Daily Cron | Sync provider data for dropdowns |
| `/v1/locations` | GET | Fetch location details | Daily Cron | Sync locations for scheduling |
| `/v1/operatories` | GET | Fetch operatory list | Daily Cron | Sync operatories for scheduling |
| `/v1/scheduletemplates` | GET | Fetch schedule templates | Daily Cron | Sync availability templates |

### Write Operations (App → Postgres → EHR)

| Endpoint | Method | Action | Cadence | Use Case |
|----------|--------|--------|---------|----------|
| `/v1/patients` | POST | Create new patient | On-demand | New patient registration via call |
| `/v1/patients/{id}` | PUT | Update patient info | On-demand | Patient info update via call |
| `/v1/appointments` | POST | Create new appointment | On-demand | Book appointment via call |
| `/v1/appointments/{id}` | PUT | Update appointment | On-demand | Reschedule/confirm/cancel via call |
| `/v1/scheduletemplates` | POST | Create schedule template | On-demand | Define provider availability |

### Authentication

| Endpoint | Method | Action | Cadence | Use Case |
|----------|--------|--------|---------|----------|
| `/oauth/client_credential/accesstoken` | POST | Get OAuth token | On token expiry | All API calls require bearer token |

---

## Access Management

### OAuth 2.0 Client Credentials Flow

Dentrix API uses OAuth 2.0 Client Credentials grant type for server-to-server authentication.

```
┌─────────────┐                              ┌─────────────┐
│   Confido   │                              │   Dentrix   │
│    App      │                              │    API      │
└──────┬──────┘                              └──────┬──────┘
       │                                            │
       │  1. POST /oauth/client_credential/accesstoken
       │     + client_id, client_secret             │
       │────────────────────────────────────────────►
       │                                            │
       │  2. { access_token, expires_in }           │
       │◄────────────────────────────────────────────
       │                                            │
       │  3. API Request + Bearer token             │
       │────────────────────────────────────────────►
       │                                            │
       │  4. API Response                           │
       │◄────────────────────────────────────────────
       │                                            │
```

### Token Endpoint

**Endpoint:** `POST /oauth/client_credential/accesstoken`

**URL:** `https://test.hs1api.com/oauth/client_credential/accesstoken?grant_type=client_credentials`

**Request:**

| Parameter | Location | Required | Description |
|-----------|----------|----------|-------------|
| `grant_type` | Query | Yes | Must be `client_credentials` |
| `client_id` | Body | Yes | API client ID |
| `client_secret` | Body | Yes | API client secret |
| `Organization-ID` | Header | Yes | Organization identifier |
| `Content-Type` | Header | Yes | `application/x-www-form-urlencoded` |

**Example Request:**

```bash
curl -X POST "https://test.hs1api.com/oauth/client_credential/accesstoken?grant_type=client_credentials" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "Organization-ID: 698343a79cf86dfc5c6c3a52" \
  -d "client_id=YOUR_CLIENT_ID&client_secret=YOUR_CLIENT_SECRET"
```

**Response (200 OK):**

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": "3600"
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `access_token` | string | Bearer token for API calls |
| `token_type` | string | Always "Bearer" |
| `expires_in` | string | Token validity in seconds (typically 3600 = 1 hour) |

### Token Caching Strategy

```python
# Token cache structure
_token_cache = {
    "token": None,
    "expires_at": 0  # Unix timestamp
}

# Refresh token 5 minutes before expiry
def get_access_token():
    if _token_cache["token"] and _token_cache["expires_at"] > time.time():
        return _token_cache["token"]  # Return cached token

    # Fetch new token
    response = requests.post(token_url, ...)

    # Cache with buffer (expire 5 min early)
    _token_cache["token"] = response["access_token"]
    _token_cache["expires_at"] = time.time() + int(response["expires_in"]) - 300

    return _token_cache["token"]
```

### Required Headers for API Calls

All API requests must include:

| Header | Value | Description |
|--------|-------|-------------|
| `Authorization` | `Bearer {access_token}` | OAuth token |
| `Organization-ID` | `{org_id}` | Organization identifier |
| `Content-Type` | `application/json` | For POST/PUT requests |

### Authentication Error Handling

| Status | Error | Action |
|--------|-------|--------|
| 401 | Token expired/invalid | Clear cache, refresh token, retry once |
| 403 | Insufficient permissions | Log error, do not retry |

**Implementation:**

```python
if response.status_code in [401, 403]:
    # Clear cached token
    _token_cache["token"] = None

    if retry_count < 1:
        # Retry once with fresh token
        return make_request(retry_count + 1)

    return None, "Authentication failed"
```

### Security Best Practices

| Practice | Implementation |
|----------|----------------|
| **Credential Storage** | Environment variables (`.env`) or secret manager |
| **Never commit secrets** | `.env` is in `.gitignore` |
| **Token caching** | Cache tokens in memory, not persistent storage |
| **HTTPS only** | All API calls use TLS 1.2+ |
| **Minimal scope** | Request only necessary permissions |

### Environment Variables

```bash
# .env file (never commit this)
DENTRIX_CLIENT_ID=your_client_id
DENTRIX_CLIENT_SECRET=your_client_secret
DENTRIX_ORG_ID=your_organization_id

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key
```

### Streamlit Cloud Secrets

For deployment on Streamlit Cloud, add secrets in the dashboard:

```toml
# .streamlit/secrets.toml (template)
DENTRIX_CLIENT_ID = "your_client_id"
DENTRIX_CLIENT_SECRET = "your_client_secret"
DENTRIX_ORG_ID = "your_organization_id"
```

---

## Schedule Templates API

Schedule templates define provider availability blocks for appointment booking.

### Create Schedule Template

**Endpoint:** `POST /v1/scheduletemplates`

**Headers:**
| Header | Type | Required | Description |
|--------|------|----------|-------------|
| `Authorization` | string | Yes | Bearer token |
| `Organization-ID` | string | Yes | Organization identifier |

**Request Body:**

```json
{
  "title": "Morning Appointments",
  "color": "FFCA00",
  "start": "09:00",
  "end": "14:00",
  "bookOnline": true,
  "dayOfWeek": "MONDAY",
  "bookingTypes": ["TREATMENT", "RECARE", "NEW_PATIENT", "EXISTING_PATIENT"],
  "reasons": [
    { "id": 12345 }
  ],
  "location": {
    "id": "12000000047595",
    "type": "LocationV1"
  },
  "operatory": {
    "id": "12000000047596",
    "type": "OperatoryV1"
  },
  "providers": [
    {
      "id": "12000000047597",
      "type": "ProviderV1"
    }
  ]
}
```

**Request Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | Yes | Template name |
| `color` | string | Yes | Hex color code (without #) |
| `start` | string | Yes | Start time (HH:MM format) |
| `end` | string | Yes | End time (HH:MM format) |
| `bookOnline` | boolean | Yes | Allow online booking |
| `dayOfWeek` | string | Yes | Day of week (SUNDAY, MONDAY, etc.) |
| `bookingTypes` | array | No | Allowed booking types |
| `reasons` | array | No | Appointment reasons |
| `location` | object | Yes | Location reference |
| `operatory` | object | Yes | Operatory reference |
| `providers` | array | Yes | Provider references |

**Day of Week Options:**
- `SUNDAY`
- `MONDAY`
- `TUESDAY`
- `WEDNESDAY`
- `THURSDAY`
- `FRIDAY`
- `SATURDAY`

**Booking Type Options:**
- `TREATMENT`
- `RECARE`
- `NEW_PATIENT`
- `EXISTING_PATIENT`

**Response (201 Created):**

```json
{
  "data": {
    "id": 324324234,
    "title": "Morning Appointments",
    "color": "FFCA00",
    "start": "09:00",
    "end": "14:00",
    "bookOnline": true,
    "dayOfWeek": "MONDAY",
    "bookingTypes": ["TREATMENT", "RECARE"],
    "location": {
      "id": "12000000047595",
      "type": "LocationV1",
      "url": "https://api.example.com/v1/locations/12000000047595"
    },
    "operatory": {
      "id": "12000000047596",
      "type": "OperatoryV1",
      "url": "https://api.example.com/v1/operatories/12000000047596"
    },
    "providers": [...]
  },
  "warnings": []
}
```

**Error Responses:**

| Status | Description |
|--------|-------------|
| 400 | Validation error - invalid request body |
| 401 | Unauthorized - invalid/expired token |
| 403 | Forbidden - insufficient permissions |
| 404 | Not found - invalid resource reference |
| 408 | Request timeout |
| 429 | Rate limited - check Retry-After header |
| 500 | Internal server error |

---

## Rate Limits

| Environment | Rate Limit | Daily Limit |
|-------------|------------|-------------|
| Sandbox | 15 req/sec | 50,000/day |
| Production | 100 req/sec | 500,000/day |

**Rate Limit Handling:**
- On 429 response, read `Retry-After` header
- Wait specified seconds before retrying
- Implement exponential backoff for repeated failures

---

## Expected API Call Volume

| Operation | Calls/Day | Notes |
|-----------|-----------|-------|
| Daily Sync (Cron) | ~100-150 | Patients, appointments, providers, operatories |
| Inbound Calls | ~150-180 | Patient verification, appointment queries |
| CRUD Operations | ~100-120 | Create/update patients & appointments |
| **Total** | **350-400** | |

---

## Peak Usage Patterns

| Time Window | Usage Level | Activity |
|-------------|-------------|----------|
| 6:00-7:00 AM | Medium | Daily sync cron job |
| 8:00-10:00 AM | **High** | Morning rush - patients confirming/rescheduling |
| 10:00-12:00 PM | Low-Medium | Steady inbound calls |
| 12:00-1:00 PM | **High** | Lunch hour - patients calling during break |
| 1:00-4:00 PM | Medium | Appointment queries, updates |
| 4:00-5:30 PM | **High** | End-of-day confirmations |
| 5:30 PM-6:00 AM | Low | Minimal activity |

**Weekly Pattern:**
- **Monday**: Highest volume (weekend backlog)
- **Tuesday-Thursday**: Steady moderate volume
- **Friday**: Elevated (weekend prep)
- **Weekend**: Minimal
