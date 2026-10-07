# Billing & Access Token Gate (DUE-067)

Pay-per-Job model with Access Token gating for Vozonda providers.

## Quick Start

### Enable Billing

Set environment variable to enable billing system:

```bash
export VOZONDA_ENABLE_BILLING=true
```

### Define Job Costs

Customize costs per provider and job type (satoshis):

```bash
export VOZONDA_COSTS='{
  "qwen": {"standard": 1000, "digest": 2000, "research": 3000},
  "nemo": {"standard": 1500, "digest": 2500, "research": 3500},
  "voxtral": {"standard": 800, "digest": 1500, "research": 2500},
  "piper": {"standard": 500, "digest": 1000, "research": 1500}
}'
```

## Architecture

### Database Schema

Three new tables in the jobs database:

- **user_accounts**: user_id, balance_sats, created_at, updated_at, metadata
- **access_tokens**: id, token_hash, user_id, created_at, last_used, active, name, metadata
- **job_charges**: id, job_id, user_id, provider, job_type, amount_sats, charged_at, status

### Flow

1. Client creates job with `access_token` in request body
2. API validates token and extracts user_id
3. Job pipeline charges user before processing:
   - Token validated again
   - Cost calculated (provider + job_type)
   - Balance checked
   - Charge record created, balance deducted
4. On job completion: charge marked "confirmed"
5. On job failure: charge marked "refunded", balance restored

## API Endpoints

### Token Management

#### Create Access Token
```bash
POST /billing/tokens
{
  "user_id": "user-123",
  "name": "CLI Token"
}
# Returns: {"token": "...", "id": "...", "created_at": ...}
```

**Auth:** Operator write auth (VOZONDA_TOKEN bearer).

**Important:** Token is only returned once. Store immediately.

#### List Tokens
```bash
GET /billing/tokens/{user_id}
# Returns: {"tokens": [...]}
```

**Auth:** Operator write auth (VOZONDA_TOKEN bearer) OR a valid access token whose `user_id`
equals the path parameter. Unauthenticated requests get 401; a valid token of another user
gets 403.

#### Revoke Token
```bash
POST /billing/tokens/{token_id}/revoke
# Returns: {"revoked": "token-id"}
```

**Auth:** Operator write auth (VOZONDA_TOKEN bearer).

### Balance Management

#### Get Balance
```bash
GET /billing/balance/{user_id}
# Returns: {"user_id": "...", "balance_sats": 5000}
```
**Auth:** Operator write auth (`VOZONDA_TOKEN` bearer) or a valid access token belonging to
`{user_id}` (via `Authorization: Bearer <token>` or `?token=<token>`).

#### Add Balance (Top-up)
```bash
POST /billing/balance/{user_id}
{
  "amount_sats": 5000
}
# Returns: {"user_id": "...", "balance_sats": 10000}
```
**Auth:** Operator write auth (`VOZONDA_TOKEN` bearer).

### Charge History

#### List User Charges
```bash
GET /billing/charges/{user_id}?limit=50
# Returns: {"user_id": "...", "charges": [...]}
```
**Auth:** Operator write auth (`VOZONDA_TOKEN` bearer) or a valid access token belonging to
`{user_id}` (via `Authorization: Bearer <token>` or `?token=<token>`).

## Job Creation with Billing

Include `access_token` when creating a job:

```bash
POST /jobs
{
  "url": "https://example.com/article",
  "style": "balanced",
  "access_token": "your_token_here"
}
```

The token is validated, and the job is charged immediately if balance is sufficient.

## Error Handling

### Authentication Errors

#### Missing or Invalid Token (401)
Returned when no token is provided or the token is invalid.
```json
{"detail": "missing or invalid token"}
```

#### Forbidden (403)
Returned when a valid access token belongs to a different user than the one in the path.
```json
{"detail": "forbidden"}
```
Only the token owner or the operator (with `VOZONDA_TOKEN` bearer) can read billing data.

### Invalid Token
```json
{
  "detail": "invalid or inactive access token: invalid token"
}
```
**Status:** 401

### Insufficient Balance
Job creation fails with error indicating insufficient balance. Charge is NOT created.
**Status:** During job processing, if balance is insufficient, the job fails and charge is refunded.

### Billing Disabled
All billing endpoints return 503 if `VOZONDA_ENABLE_BILLING` is false.

## Provider Integration

### Qwen Provider
File: `apps/api/src/vozonda_api/providers/qwen.py`

Validates access token and charges before rendering:
```python
await render_audio(
    script=lines,
    workdir=workdir,
    access_token=token,
    job_id=job_id
)
```

### Nemo Provider
File: `apps/api/src/vozonda_api/providers/nemo.py`

Same interface as Qwen with billing support.

## Charge States

- **pending**: Charge created, balance deducted
- **confirmed**: Job completed successfully
- **refunded**: Job failed, balance restored

## Configuration

### Environment Variables

```bash
# Enable/disable billing system
VOZONDA_ENABLE_BILLING=true|false

# Custom cost matrix (JSON)
VOZONDA_COSTS='{"provider": {"job_type": cost_in_sats}}'

# Database path (default: data/jobs.db)
VOZONDA_DB=/path/to/jobs.db
```

## Testing

### Create Test User with Balance

```python
from vozonda_api.billing import create_user, add_user_balance, create_access_token

# Create user with 10000 sats
user = create_user("test-user", initial_balance_sats=10000)

# Create access token
token, info = create_access_token("test-user", name="test-token")
print(f"Token: {token}")

# Check balance
from vozonda_api.billing import get_user_balance
balance = get_user_balance("test-user")
print(f"Balance: {balance} sats")
```

### Create Job with Token

```bash
curl -X POST http://127.0.0.1:8787/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/article",
    "access_token": "YOUR_TOKEN_HERE"
  }'
```

## Security Considerations

1. **Tokens stored as hashes**: plaintext tokens never stored in database
2. **Tokens are single-use on creation**: client must store immediately
3. **Token validation on every job**: prevents stale tokens
4. **No plaintext tokens in logs**: authorization header masked
5. **HTTPS recommended**: for production deployment

## Future Enhancements

- Lightning Network integration for payment
- Subscription tiers with refill schedules
- Usage analytics and cost estimates
- Rate limiting based on account tier
- Promotional credits system
