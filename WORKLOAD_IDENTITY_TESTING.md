# Testing Guide for Workload Identity Federation

This guide explains how to test the Workload Identity Federation implementation for Google Cloud services.

## Prerequisites

1. **Google Cloud Project** with Workload Identity Federation configured
2. **PostHog instance** with the Workload Identity Federation code deployed
3. **RSA key pair** generated for signing JWT tokens
4. **Test team/organization** in PostHog

## Setup Steps

### 1. Generate RSA Keys for JWT Signing

```bash
python manage.py generate_workload_identity_key --key-size 2048 --validity-days 365
```

This creates an RSA key pair that will be used to sign JWT tokens.

### 2. Configure Workload Identity Pool in Google Cloud

#### Create Workload Identity Pool

```bash
gcloud iam workload-identity-pools create posthog-pool \
    --location=global \
    --display-name="PostHog Workload Identity Pool"
```

#### Create OIDC Provider

```bash
gcloud iam workload-identity-pools providers create-oidc posthog-provider \
    --location=global \
    --workload-identity-pool=posthog-pool \
    --issuer-uri="https://your-posthog-instance.com/workload-identity" \
    --allowed-audiences="//iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/posthog-pool/providers/posthog-provider" \
    --attribute-mapping="google.subject=assertion.sub,attribute.organization_id=assertion.organization_id,attribute.project_id=assertion.project_id" \
    --attribute-condition="assertion.organization_id == 'YOUR_ORG_ID'"
```

**Important**: Replace:
- `your-posthog-instance.com` with your actual PostHog URL
- `PROJECT_NUMBER` with your Google Cloud project number
- `YOUR_ORG_ID` with your PostHog organization ID

#### Grant Permissions to Service Account

```bash
# Create or use existing service account
gcloud iam service-accounts create posthog-workload-sa \
    --display-name="PostHog Workload Identity Service Account"

# Grant BigQuery permissions
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
    --member="serviceAccount:posthog-workload-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/bigquery.dataViewer"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
    --member="serviceAccount:posthog-workload-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/bigquery.jobUser"

# Allow Workload Identity Pool to impersonate service account
gcloud iam service-accounts add-iam-policy-binding posthog-workload-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
    --role=roles/iam.workloadIdentityUser \
    --member="principalSet://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/posthog-pool/attribute.organization_id/YOUR_ORG_ID"
```

### 3. Configure PostHog Team

Create a `WorkloadIdentityConfig` for your test team:

```python
from posthog.models import Team, WorkloadIdentityConfig

team = Team.objects.get(id=YOUR_TEAM_ID)

WorkloadIdentityConfig.objects.create(
    team=team,
    audience="//iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/posthog-pool/providers/posthog-provider",
    google_cloud_project_id="YOUR_PROJECT_ID",
    is_enabled=True,
)
```

## Testing Procedures

### Test 1: OIDC Discovery Endpoint

**Endpoint**: `https://your-posthog-instance.com/workload-identity/.well-known/openid-configuration`

```bash
curl https://your-posthog-instance.com/workload-identity/.well-known/openid-configuration
```

**Expected Response**:
```json
{
  "issuer": "https://your-posthog-instance.com/workload-identity",
  "jwks_uri": "https://your-posthog-instance.com/workload-identity/.well-known/jwks.json",
  "subject_types_supported": ["public"],
  "response_types_supported": ["id_token"],
  "claims_supported": [
    "sub", "aud", "exp", "iat", "iss", "nbf",
    "organization_id", "project_id", "project_name", "project_region"
  ],
  "id_token_signing_alg_values_supported": ["RS256"],
  "scopes_supported": ["openid"]
}
```

### Test 2: JWKS Endpoint

**Endpoint**: `https://your-posthog-instance.com/workload-identity/.well-known/jwks.json`

```bash
curl https://your-posthog-instance.com/workload-identity/.well-known/jwks.json
```

**Expected Response**:
```json
{
  "keys": [
    {
      "kty": "RSA",
      "kid": "posthog-workload-identity-...",
      "use": "sig",
      "alg": "RS256",
      "n": "...",
      "e": "AQAB"
    }
  ]
}
```

**Verify**: The response should contain at least one active key.

### Test 3: Internal Token Generation

Test the internal token generation function:

```python
from posthog.api.workload_identity import generate_workload_identity_token

# Generate a token
token = generate_workload_identity_token(
    team_id=YOUR_TEAM_ID,
    audience="//iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/posthog-pool/providers/posthog-provider",
    service_type="bigquery",
    service_id="test-source-123",
)

print("Generated token:", token)
```

**Verify**: 
- Function should return a JWT token (string)
- Decode the token (using jwt.decode without verification) to inspect claims
- Should contain: `organization_id`, `project_id`, `project_name`, `project_region`, `service_type`, `service_id`

### Test 4: Token Validation (JWT Structure)

```python
import jwt

# Decode without verification to inspect structure
decoded = jwt.decode(token, options={"verify_signature": False})
print("Token claims:", decoded)

# Verify required claims
assert "iss" in decoded
assert "sub" in decoded
assert "aud" in decoded
assert "exp" in decoded
assert "iat" in decoded
assert "organization_id" in decoded
assert "project_id" in decoded
```

### Test 5: Google STS Token Exchange

```python
from posthog.google_cloud_sts import GoogleSTSClient

client = GoogleSTSClient()

# Exchange token
response = client.exchange_token(
    subject_token=token,
    audience="//iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/posthog-pool/providers/posthog-provider",
)

print("STS Response:", response)
```

**Expected Response**:
```python
{
    'access_token': 'ya29.c.b0...',
    'issued_token_type': 'urn:ietf:params:oauth:token-type:access_token',
    'token_type': 'Bearer',
    'expires_in': 3600
}
```

**Verify**:
- `access_token` is present
- Token type is "Bearer"
- Expires in 3600 seconds (1 hour)

### Test 6: Full Authentication Flow

```python
from posthog.google_cloud_helpers import get_google_cloud_access_token

# Get access token (combines OIDC generation + STS exchange)
access_token = get_google_cloud_access_token(
    team_id=YOUR_TEAM_ID,
    audience="//iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/posthog-pool/providers/posthog-provider",
    service_type="bigquery",
    service_id="test-source-123",
)

print("Access token:", access_token)
```

### Test 7: BigQuery Client with Workload Identity

```python
from posthog.google_cloud_helpers import bigquery_client_with_workload_identity

with bigquery_client_with_workload_identity(
    team_id=YOUR_TEAM_ID,
    audience="//iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/posthog-pool/providers/posthog-provider",
    project_id="YOUR_PROJECT_ID",
    service_type="bigquery",
    service_id="test-source-123",
) as client:
    # Test listing datasets
    datasets = list(client.list_datasets())
    print(f"Datasets: {[d.dataset_id for d in datasets]}")
    
    # Test querying
    query = "SELECT 1 as test"
    result = client.query(query).result()
    print(f"Query result: {list(result)}")
```

**Verify**:
- Client can list datasets
- Client can execute queries
- No authentication errors

### Test 8: Cloud Storage Client with Workload Identity

```python
from posthog.google_cloud_helpers import storage_client_with_workload_identity

with storage_client_with_workload_identity(
    team_id=YOUR_TEAM_ID,
    audience="//iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/posthog-pool/providers/posthog-provider",
    project_id="YOUR_PROJECT_ID",
    service_type="storage",
    service_id="test-destination-456",
) as client:
    # Test listing buckets
    buckets = list(client.list_buckets())
    print(f"Buckets: {[b.name for b in buckets]}")
```

## Troubleshooting

### Issue: "No active signing key available"

**Solution**: Generate a key using the management command:
```bash
python manage.py generate_workload_identity_key
```

### Issue: "Team with id X does not exist"

**Solution**: Verify the team_id is correct:
```python
from posthog.models import Team
team = Team.objects.get(id=YOUR_TEAM_ID)
print(f"Team: {team.name}, Org: {team.organization_id}")
```

### Issue: Google STS returns 403 or 401

**Possible causes**:
1. **Attribute condition doesn't match**: Check that `organization_id` in token matches the condition in Google Cloud
2. **Audience mismatch**: Verify the audience URL is exactly the same in both PostHog and Google Cloud
3. **JWKS not accessible**: Ensure Google Cloud can access your JWKS endpoint

**Debug**:
```bash
# Test JWKS accessibility from external network
curl https://your-posthog-instance.com/workload-identity/.well-known/jwks.json

# Decode token to inspect claims
python -c "import jwt, sys; print(jwt.decode(sys.argv[1], options={'verify_signature': False}))" "YOUR_TOKEN"
```

### Issue: "Failed to authenticate with provided credentials"

**Solution**: Check service account permissions:
```bash
gcloud projects get-iam-policy YOUR_PROJECT_ID \
    --flatten="bindings[].members" \
    --filter="bindings.members:serviceAccount:posthog-workload-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com"
```

## Security Testing

### Test Organization Isolation

1. Create tokens for different organizations
2. Verify that Google Cloud rejects tokens from organizations not in the attribute condition
3. Try accessing resources with wrong organization_id in token

### Test Token Expiration

1. Generate a token
2. Wait for expiration (default 1 hour)
3. Verify that expired tokens are rejected by Google STS

### Test Key Rotation

1. Generate a new key: `python manage.py generate_workload_identity_key --deactivate-old`
2. Verify old tokens still work during grace period
3. Verify new tokens use the new key

## Automated Testing

Run the test suite:

```bash
pytest posthog/api/test/test_workload_identity.py -v
```

## Monitoring

Check logs for token generation and exchange:

```bash
# Token generation logs
grep "workload_identity_token_generated" /var/log/posthog.log

# STS exchange logs
grep "google_sts_token_exchange" /var/log/posthog.log
```

## Success Criteria

✅ OIDC discovery endpoint returns valid configuration  
✅ JWKS endpoint returns active keys  
✅ Token generation creates valid JWT with correct claims  
✅ Google STS successfully exchanges tokens  
✅ BigQuery client can authenticate and query  
✅ Cloud Storage client can authenticate and list buckets  
✅ Attribute conditions properly restrict access by organization  
✅ Token expiration is enforced  
✅ Key rotation works without downtime
