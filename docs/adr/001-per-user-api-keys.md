# ADR-001: Per-User API Keys for Multi-Tenant SaaS Support

## Status
Proposed

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

### 1. User Model Changes

Add API key fields to the existing `User` model (Polar users, not admin users):

```python
class User(Base):
    # Existing fields
    polar_user_id: str          # Primary key from Polar
    access_token: str           # Polar OAuth token (encrypted)
    refresh_token: str          # Polar refresh token (encrypted)

    # New fields
    api_key_hash: str | None    # Hashed API key for external access
    api_key_prefix: str | None  # First 8 chars for identification (pfk_abc123...)
    api_key_created_at: datetime | None
    api_key_last_used_at: datetime | None
```

### 2. API Key Format

```
pfk_<user_id_prefix>_<random_32_chars>
Example: pfk_12345678_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
```

- `pfk_` prefix identifies it as a polar-flow-server key
- `user_id_prefix` helps identify which user (first 8 chars)
- 32 random chars for security
- Only the hash is stored, full key shown once on creation

### 3. Authentication Flow

```python
# API request
GET /api/v1/users/{user_id}/sleep
Header: X-API-Key: pfk_12345678_xxxxx

# Server validates:
1. Hash the provided key
2. Find user by api_key_hash
3. Verify user.polar_user_id == {user_id} in path
4. If mismatch → 403 Forbidden
5. Update api_key_last_used_at
```

### 4. OAuth Flow Changes

When OAuth completes and a user connects their Polar account:

```python
# After successful OAuth token exchange
1. Create/update User with Polar tokens
2. Generate new API key
3. Return to callback URL with:
   - polar_user_id
   - api_key (only time it's shown in full)

# Callback URL example:
https://myloopcoach.com/polar/callback?
  polar_user_id=12345678
  &api_key=pfk_12345678_xxxxx
  &status=connected
```

### 5. New API Endpoints

```
POST /api/v1/users/{user_id}/api-key/regenerate
  - Requires current valid API key
  - Invalidates old key, returns new one
  - Use case: key rotation, suspected compromise

GET /api/v1/users/{user_id}/status
  - Returns connection status, last sync, etc.
  - Requires valid API key for that user
```

### 6. Admin vs User Keys

| Type | Scope | Use Case |
|------|-------|----------|
| Admin session | Full server access | Dashboard, server management |
| User API key | Single user's data | Laravel API calls, external apps |

Admins can still view all data via dashboard, but API keys are scoped.

### 7. Backward Compatibility

For self-hosted single-user deployments:
- Existing single API key mode continues to work (via `API_KEY` env var)
- If `API_KEY` is set, it acts as a "master key" with full access
- Per-user keys work alongside this for SaaS deployments

## Consequences

### Positive
- **Security**: Compromised key only affects one user
- **Audit**: Can track which user's key made each request
- **Revocation**: Can revoke single user's access without affecting others
- **SaaS-ready**: Proper multi-tenant isolation

### Negative
- **Complexity**: More auth logic to maintain
- **Migration**: Existing integrations need to update
- **Key management**: Users need to store keys securely

### Neutral
- **Storage**: Additional columns in users table
- **Performance**: One extra DB lookup per request (cached in practice)

## Implementation Plan

### Phase 1: Database & Model
- [ ] Add migration for new User columns
- [ ] Update User model with API key fields
- [ ] Add API key generation utility

### Phase 2: Authentication
- [ ] Create new auth guard for per-user keys
- [ ] Update data endpoints to use new guard
- [ ] Add key validation and user scoping

### Phase 3: OAuth Integration
- [ ] Modify OAuth callback to generate API key
- [ ] Add API key to callback redirect params
- [ ] Create key regeneration endpoint

### Phase 4: Admin Dashboard
- [ ] Show user's API key status in admin
- [ ] Allow admin to revoke/regenerate user keys
- [ ] Add last-used tracking display

### Phase 5: Documentation
- [ ] Update API docs with new auth model
- [ ] Add Laravel integration guide
- [ ] Document key rotation best practices

## Files to Create/Modify

| File | Changes |
|------|---------|
| `alembic/versions/xxx_add_user_api_keys.py` | New migration |
| `src/polar_flow_server/models/user.py` | Add API key fields |
| `src/polar_flow_server/core/api_keys.py` | Key generation/validation |
| `src/polar_flow_server/api/auth.py` | Per-user auth guard |
| `src/polar_flow_server/api/data.py` | Update to use new guard |
| `src/polar_flow_server/admin/routes.py` | OAuth callback changes |
| `docs/api-authentication.md` | New documentation |

## Open Questions

1. **Key expiration**: Should API keys expire? (Recommend: No, but track last_used)
2. **Rate limiting**: Per-key rate limits? (Recommend: Yes, future enhancement)
3. **Multiple keys per user**: Allow multiple keys? (Recommend: No, keep simple)
