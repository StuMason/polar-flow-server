# ADR-001: Per-User API Keys for Multi-Tenant SaaS Support

## Status
Proposed (Revised based on security review)

## Context

polar-flow-server is designed to work in two modes:

1. **Self-hosted**: Single user boots up an instance, connects their Polar account, uses dashboard or API
2. **SaaS backend**: Laravel frontend (myloopcoach.com) manages users, polar-flow-server handles Polar data sync/storage

The current authentication model uses a single API key for all external access. This creates a security risk for SaaS deployments: if the single key is compromised, ALL users' data is exposed.

### Current Architecture
```
Laravel App                     polar-flow-server
┌─────────────┐                ┌─────────────────┐
│ All users   │──ONE API KEY──▶│ All data        │
│ share key   │                │ accessible      │
└─────────────┘                └─────────────────┘

Risk: Key compromise = total data breach
```

### Proposed Architecture
```
Laravel App                     polar-flow-server
┌─────────────┐                ┌─────────────────┐
│ Steve       │──Steve's key──▶│ Steve's data    │
│ Jane        │──Jane's key───▶│ Jane's data     │
│ Bob         │──Bob's key────▶│ Bob's data      │
└─────────────┘                └─────────────────┘

Risk: Key compromise = single user's data only
```

## Decision

Implement per-user API keys with the following design:

### 1. Extend Existing APIKey Model

The codebase already has an `APIKey` model for service-level authentication. We extend it to support per-user scoping:

```python
class APIKey(Base):
    """API key for authenticating service-to-service requests."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(12), index=True)  # First 8 chars for identification
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True, index=True)

    # NEW: User scoping (nullable for service-level keys)
    user_id: Mapped[str | None] = mapped_column(
        String(50),
        ForeignKey("users.polar_user_id"),
        nullable=True,
        index=True
    )

    # Rate limiting
    rate_limit_requests: Mapped[int] = mapped_column(default=1000)  # per hour
    rate_limit_remaining: Mapped[int] = mapped_column(default=1000)
    rate_limit_reset_at: Mapped[datetime | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Relationship
    user: Mapped["User | None"] = relationship(back_populates="api_keys")
```

**Key behaviors:**
- `user_id = None`: Service-level key with full access (existing behavior)
- `user_id = "12345"`: User-scoped key, can only access that user's data

### 2. API Key Format

```
pfk_<random_40_chars>
Example: pfk_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0
```

- `pfk_` prefix identifies it as a polar-flow-server key
- 40 random alphanumeric chars for security (240 bits of entropy)
- **No user ID in the key** - prevents enumeration attacks
- First 8 chars stored as `key_prefix` for admin identification
- Only the hash is stored, full key shown once on creation

### 3. Authentication Flow

```python
# API request
GET /api/v1/users/{user_id}/sleep
Header: X-API-Key: pfk_a1b2c3d4e5f6...

# Server validates (in this order):
async def api_key_guard(connection: ASGIConnection, handler: BaseRouteHandler) -> None:
    api_key = connection.headers.get("X-API-Key")
    if not api_key:
        raise NotAuthorizedException("Missing X-API-Key header")

    # 1. Hash and lookup key
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    key_record = await get_api_key_by_hash(key_hash, session)

    if not key_record or not key_record.is_active:
        raise NotAuthorizedException("Invalid or inactive API key")

    # 2. Check rate limit BEFORE any data access
    if not await check_rate_limit(key_record, session):
        raise TooManyRequestsException("Rate limit exceeded", retry_after=...)

    # 3. If user-scoped key, verify access to requested user
    path_user_id = connection.path_params.get("user_id")
    if key_record.user_id is not None:
        if path_user_id and key_record.user_id != path_user_id:
            raise NotAuthorizedException("API key not authorized for this user")

    # 4. Update last_used_at
    key_record.last_used_at = datetime.now(UTC)
```

### 4. Secure OAuth Flow (Two-Step Code Exchange)

**CRITICAL SECURITY FIX**: API keys are NEVER passed in URL parameters. Instead, we use a temporary authorization code that Laravel exchanges server-to-server.

```
┌─────────┐          ┌─────────────────┐          ┌─────────────┐
│  User   │          │  polar-flow     │          │   Laravel   │
│ Browser │          │    server       │          │   Backend   │
└────┬────┘          └────────┬────────┘          └──────┬──────┘
     │                        │                          │
     │ 1. User clicks         │                          │
     │    "Connect Polar"     │                          │
     │───────────────────────▶│                          │
     │                        │                          │
     │ 2. Redirect to         │                          │
     │    Polar OAuth         │                          │
     │◀───────────────────────│                          │
     │                        │                          │
     │ 3. User authorizes     │                          │
     │    on Polar            │                          │
     │───────────────────────▶│                          │
     │                        │                          │
     │ 4. Polar redirects     │                          │
     │    with OAuth code     │                          │
     │───────────────────────▶│                          │
     │                        │                          │
     │                        │ 5. Exchange OAuth code   │
     │                        │    for Polar tokens      │
     │                        │                          │
     │                        │ 6. Generate temp auth    │
     │                        │    code (expires 5min)   │
     │                        │                          │
     │ 7. Redirect to Laravel │                          │
     │    with temp code only │                          │
     │◀───────────────────────│                          │
     │                        │                          │
     │ 8. Browser follows     │                          │
     │    redirect            │                          │
     │────────────────────────────────────────────────▶  │
     │                        │                          │
     │                        │  9. Server-to-server     │
     │                        │     POST with temp code  │
     │                        │◀─────────────────────────│
     │                        │                          │
     │                        │ 10. Validate code,       │
     │                        │     generate API key,    │
     │                        │     return in response   │
     │                        │─────────────────────────▶│
     │                        │                          │
     │                        │                          │ 11. Store API key
     │                        │                          │     securely
```

**Step-by-step:**

1. User initiates OAuth from Laravel app
2. Laravel redirects to polar-flow-server OAuth start (with Laravel callback URL)
3. polar-flow-server redirects to Polar OAuth
4. User authorizes on Polar
5. Polar redirects back with authorization code
6. polar-flow-server exchanges code for tokens, stores user
7. Generate temporary auth code (random 64 chars, expires in 5 minutes, single-use)
8. Redirect to Laravel callback with ONLY:
   ```
   https://myloopcoach.com/polar/callback?
     code=temp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
     &polar_user_id=12345678
     &status=connected
   ```
9. Laravel backend makes server-to-server POST request:
   ```
   POST /api/v1/oauth/exchange
   Content-Type: application/json

   {
     "code": "temp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
     "client_id": "laravel_app_id"
   }
   ```
10. polar-flow-server validates code, generates API key, returns:
    ```json
    {
      "api_key": "pfk_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0",
      "polar_user_id": "12345678",
      "expires_at": null
    }
    ```
11. Laravel stores API key encrypted in database

**Why this is secure:**
- API key never appears in browser history, server logs, or referrer headers
- Temporary code is single-use and expires quickly
- Server-to-server exchange requires client credentials
- No sensitive data in URL parameters

### 5. New API Endpoints

```
POST /api/v1/oauth/exchange
  - Exchange temporary auth code for API key
  - Requires: valid temp code, client credentials
  - Returns: API key, user ID

POST /api/v1/users/{user_id}/api-key/regenerate
  - Requires current valid API key for that user
  - Invalidates old key, returns new one
  - Use case: key rotation, suspected compromise

POST /api/v1/users/{user_id}/api-key/revoke
  - Requires current valid API key OR admin auth
  - Permanently invalidates key without generating new one
  - Use case: user disconnects, account deletion

GET /api/v1/users/{user_id}/status
  - Returns connection status, last sync, key info (masked)
  - Requires valid API key for that user
```

### 6. Rate Limiting (Phase 1 - Critical)

Rate limiting is implemented at the API key level:

```python
# Default limits
DEFAULT_RATE_LIMIT = 1000  # requests per hour

async def check_rate_limit(key: APIKey, session: AsyncSession) -> bool:
    """Check and update rate limit for API key."""
    now = datetime.now(UTC)

    # Reset if window expired
    if key.rate_limit_reset_at is None or now >= key.rate_limit_reset_at:
        key.rate_limit_remaining = key.rate_limit_requests
        key.rate_limit_reset_at = now + timedelta(hours=1)

    # Check limit
    if key.rate_limit_remaining <= 0:
        return False

    # Decrement
    key.rate_limit_remaining -= 1
    return True
```

Response headers:
```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 847
X-RateLimit-Reset: 1704067200
```

### 7. Admin vs User Keys

| Type | Scope | Use Case | user_id |
|------|-------|----------|---------|
| Service key | Full server access | Admin CLI, monitoring | `NULL` |
| User API key | Single user's data | Laravel API calls | User's polar_user_id |

Admins can still view all data via dashboard (session auth), but API keys are scoped.

### 8. Self-Hosted Mode

For self-hosted single-user deployments:

1. **Environment variable mode** (existing):
   - Set `API_KEY` env var for simple single-key auth
   - This key has full access (service-level)
   - No database lookup required

2. **Per-user mode** (new):
   - When user connects Polar via admin UI, per-user key is generated
   - Key is displayed ONCE on the success page (user must copy it)
   - Stored hashed in database

3. **Both modes together**:
   - `API_KEY` env var works as a master/fallback key
   - Per-user keys provide additional scoped access
   - Self-hosted users typically only need the env var key

### 9. Webhook Authentication

For Laravel-initiated sync triggers via webhooks:

```python
# Laravel can trigger sync using the user's API key
POST /api/v1/users/{user_id}/sync/trigger
X-API-Key: pfk_user_key_here

# Or use a service-level key for batch operations
POST /api/v1/sync/trigger-all
X-API-Key: pfk_service_key_here
```

Webhook callbacks FROM polar-flow-server TO Laravel use HMAC signatures:
```python
# polar-flow-server signs webhook payload
signature = hmac.new(
    webhook_secret.encode(),
    payload.encode(),
    hashlib.sha256
).hexdigest()

# Header: X-Webhook-Signature: sha256=xxxxx
```

## Consequences

### Positive
- **Security**: Compromised key only affects one user
- **Audit**: Can track which user's key made each request
- **Revocation**: Can revoke single user's access without affecting others
- **SaaS-ready**: Proper multi-tenant isolation
- **Rate limiting**: Prevents abuse per key

### Negative
- **Complexity**: More auth logic to maintain
- **Migration**: Existing integrations need to update
- **Key management**: Laravel needs to store keys securely

### Neutral
- **Storage**: Additional columns in api_keys table
- **Performance**: One extra DB lookup per request (indexed, fast)

## Implementation Plan

### Phase 1: Database, Model & Rate Limiting
- [ ] Add migration to extend APIKey model with user_id, rate limit fields
- [ ] Update APIKey model with new fields and relationships
- [ ] Add temporary auth code table for OAuth exchange
- [ ] Add API key generation utility (secure random, hashing)
- [ ] Implement rate limiting logic

### Phase 2: OAuth Integration
- [ ] Create temp code generation on OAuth success
- [ ] Create `/api/v1/oauth/exchange` endpoint
- [ ] Modify OAuth callback to return only temp code
- [ ] Update admin UI to display API key on successful connection

### Phase 3: Authentication Guard
- [ ] Create per-user auth guard with rate limit check
- [ ] Update data endpoints to use new guard
- [ ] Add key validation and user scoping
- [ ] Implement proper 401/403/429 responses

### Phase 4: Key Management Endpoints
- [ ] Create key regeneration endpoint
- [ ] Create key revocation endpoint
- [ ] Create user status endpoint
- [ ] Add CLI commands for key management

### Phase 5: Admin Dashboard
- [ ] Show user's API key status in admin
- [ ] Allow admin to revoke user keys
- [ ] Add rate limit and last-used tracking display
- [ ] Add key prefix display for identification

### Phase 6: Testing
- [ ] Unit tests for key generation and hashing
- [ ] Unit tests for rate limiting logic
- [ ] Integration tests for OAuth two-step flow
- [ ] Integration tests for auth guard
- [ ] Security tests for cross-user access attempts
- [ ] Load tests for rate limiting behavior

### Phase 7: Documentation
- [ ] Update API docs with new auth model
- [ ] Add Laravel integration guide with code examples
- [ ] Document key rotation best practices
- [ ] Document webhook authentication

## Files to Create/Modify

| File | Changes |
|------|---------|
| `alembic/versions/xxx_add_user_api_keys.py` | Migration for APIKey changes |
| `alembic/versions/xxx_add_temp_auth_codes.py` | Migration for temp codes table |
| `src/polar_flow_server/models/api_key.py` | Add user_id, rate limit fields |
| `src/polar_flow_server/models/temp_auth_code.py` | New temp code model |
| `src/polar_flow_server/core/api_keys.py` | Key generation/validation/rate limiting |
| `src/polar_flow_server/api/auth.py` | Per-user auth guard |
| `src/polar_flow_server/api/oauth.py` | New OAuth exchange endpoint |
| `src/polar_flow_server/api/data.py` | Update to use new guard |
| `src/polar_flow_server/admin/routes.py` | OAuth callback changes |
| `docs/api-authentication.md` | New documentation |

## Resolved Questions

1. **Key expiration**: No automatic expiration. Track `last_used_at` for stale key identification. Consider soft expiration (warning after 90 days) as future enhancement.

2. **Rate limiting**: Yes, implemented in Phase 1. Default 1000 requests/hour per key, configurable per key.

3. **Multiple keys per user**: No, keep simple. One active key per user. Regenerate replaces existing key.

4. **Lost API key recovery**: User can regenerate key via the polar-flow-server admin UI (if self-hosted) or request regeneration from Laravel admin (if SaaS).

5. **Existing deployment migration**:
   - Self-hosted: No change needed, `API_KEY` env var continues to work
   - SaaS: Laravel triggers reconnection flow for each user to generate per-user keys

6. **Self-hosted unused fields**: Per-user key fields exist but remain NULL until used. Minimal overhead.

7. **Performance of hash lookups**: api_keys.key_hash is indexed, lookup is O(log n). For very high traffic, add Redis caching layer.

## Security Considerations

1. **Key storage**: Only SHA-256 hash stored in database. Raw key shown once on creation.
2. **Timing attacks**: Use constant-time comparison for hash validation.
3. **Brute force**: Rate limiting + key length (40 chars) makes brute force infeasible.
4. **Key rotation**: Provide regeneration endpoint; recommend periodic rotation.
5. **Audit logging**: Log all key usage with timestamp and IP (future enhancement).
