# Workload Identity Federation Support for Google Cloud Services

## Overview

This document describes the implementation of Workload Identity Federation support for PostHog's Google Cloud integrations. This allows PostHog to authenticate with Google Cloud services without using long-lived service account keys, improving security through short-lived tokens.

## Implementation Status

### Completed
- ✅ Core authentication module (`posthog/google_cloud_auth.py`)
- ✅ BigQuery data import source (full support)

### Pending
- ⏸️ BigQuery batch exports
- ⏸️ Google Cloud Storage batch exports
- ⏸️ Google PubSub CDP templates
- ⏸️ Google Cloud Storage CDP templates
- ⏸️ Cloud SQL IAM authentication for Postgres
- ⏸️ Integration model updates
- ⏸️ Google Ads, Google Sheets (OAuth-based, different auth flow)

## Core Module: `posthog/google_cloud_auth.py`

### Key Functions

#### `get_google_credentials(auth_config, scopes)`
Creates Google credentials from either:
- **Service Account Key** (type: "service_account")
- **Workload Identity Federation** (type: "external_account")

**Service Account Example:**
```json
{
  "type": "service_account",
  "project_id": "my-project",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...",
  "private_key_id": "key123",
  "client_email": "service-account@my-project.iam.gserviceaccount.com",
  "token_uri": "https://oauth2.googleapis.com/token"
}
```

**Workload Identity Federation Example:**
```json
{
  "type": "external_account",
  "audience": "//iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL_ID/providers/PROVIDER_ID",
  "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
  "token_url": "https://sts.googleapis.com/v1/token",
  "credential_source": {
    "file": "/var/run/secrets/tokens/gcp-ksa/token"
  },
  "service_account_impersonation_url": "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/SERVICE_ACCOUNT_EMAIL:generateAccessToken"
}
```

#### `get_project_id_from_credentials(credentials, auth_config)`
Extracts the GCP project ID from credentials or configuration, handling both service accounts and external accounts.

## BigQuery Implementation

### Changes Made

1. **`bigquery_client()` context manager** - Now accepts `auth_config` parameter
2. **`bigquery_storage_read_client()` context manager** - Now accepts `auth_config` parameter  
3. **`_build_auth_config_from_key_file()`** - Helper to convert key_file config to auth_config
4. **All BigQuery helper functions** - Updated to support `auth_config` parameter

### Backwards Compatibility

All functions maintain backwards compatibility with legacy individual parameters (project_id, private_key, etc.). The new `auth_config` parameter is optional.

### UI Changes

The BigQuery source configuration now accepts **any JSON file**, not just service account keys. The upload field caption indicates support for both authentication methods.

## How to Use Workload Identity Federation

### Setup in GCP

1. **Create Workload Identity Pool**:
   ```bash
   gcloud iam workload-identity-pools create posthog-pool \
     --location=global \
     --display-name="PostHog Workload Identity Pool"
   ```

2. **Create Workload Identity Provider** (for Kubernetes):
   ```bash
   gcloud iam workload-identity-pools providers create-oidc posthog-provider \
     --location=global \
     --workload-identity-pool=posthog-pool \
     --issuer-uri=https://container.googleapis.com/v1/projects/PROJECT_ID/locations/LOCATION/clusters/CLUSTER_NAME \
     --allowed-audiences=https://container.googleapis.com/v1/projects/PROJECT_ID/locations/LOCATION/clusters/CLUSTER_NAME \
     --attribute-mapping="google.subject=assertion.sub,attribute.namespace=assertion['kubernetes.io']['namespace'],attribute.service_account_name=assertion['kubernetes.io']['serviceaccount']['name']"
   ```

3. **Grant Service Account Permissions**:
   ```bash
   gcloud iam service-accounts add-iam-policy-binding SERVICE_ACCOUNT_EMAIL \
     --role=roles/iam.workloadIdentityUser \
     --member="principal://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/posthog-pool/subject/system:serviceaccount:NAMESPACE:KSA_NAME"
   ```

4. **Grant BigQuery Permissions to Service Account**:
   ```bash
   gcloud projects add-iam-policy-binding PROJECT_ID \
     --member="serviceAccount:SERVICE_ACCOUNT_EMAIL" \
     --role="roles/bigquery.dataViewer"
   
   gcloud projects add-iam-policy-binding PROJECT_ID \
     --member="serviceAccount:SERVICE_ACCOUNT_EMAIL" \
     --role="roles/bigquery.jobUser"
   ```

5. **Generate Configuration File**:
   ```bash
   gcloud iam workload-identity-pools create-cred-config \
     projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/posthog-pool/providers/posthog-provider \
     --service-account=SERVICE_ACCOUNT_EMAIL \
     --output-file=workload-identity-config.json \
     --credential-source-file=/var/run/secrets/tokens/gcp-ksa/token
   ```

### In PostHog

Simply upload the generated `workload-identity-config.json` file when configuring a BigQuery source. PostHog will automatically detect it's an external_account configuration and use Workload Identity Federation.

## Remaining Work

### BigQuery Batch Exports

**Files to Update:**
- `products/batch_exports/backend/temporal/destinations/bigquery_batch_export.py`

**Changes Needed:**
1. Import `get_google_credentials` and `get_project_id_from_credentials`
2. Update `BigQueryInsertInputs` to accept optional `auth_config` field
3. Update `BigQueryClient` initialization to support both auth methods
4. Update activity functions to pass auth_config through

**Example Pattern:**
```python
from posthog.google_cloud_auth import get_google_credentials, get_project_id_from_credentials

# In BigQueryClient.__init__ or similar:
if auth_config:
    credentials = get_google_credentials(
        auth_config,
        scopes=["https://www.googleapis.com/auth/bigquery"]
    )
    project_id = get_project_id_from_credentials(credentials, auth_config)
else:
    # Legacy service account approach
    credentials = service_account.Credentials.from_service_account_info(...)
    project_id = inputs.project_id
```

### Google Cloud Storage

**Files to Update:**
- `products/batch_exports/backend/temporal/destinations/s3_batch_export.py` (for GCS support)
- `posthog/cdp/templates/google_cloud_storage/template_google_cloud_storage.py`

**Changes Needed:**
Similar to BigQuery - add auth_config support to GCS client initialization.

### Google PubSub

**Files to Update:**
- `posthog/cdp/templates/google_pubsub/template_google_pubsub.py`

**Changes Needed:**
Update PubSub publisher client initialization to use `get_google_credentials()`.

### Cloud SQL IAM Authentication

**Files to Update:**
- `posthog/temporal/data_imports/sources/postgres/postgres.py`
- `posthog/temporal/data_imports/sources/postgres/source.py`

**Implementation Approach:**
1. Add new field to PostgresSourceConfig for IAM authentication toggle
2. When IAM auth is enabled, generate access token using:
   ```python
   import google.auth
   import google.auth.transport.requests
   
   credentials = get_google_credentials(auth_config, ["https://www.googleapis.com/auth/cloud-platform"])
   credentials.refresh(google.auth.transport.requests.Request())
   password = credentials.token  # Use as password for psycopg connection
   ```
3. User field should be Cloud SQL IAM user email
4. Tokens expire after ~1 hour, so need to refresh on each connection

### Integration Model

**Files to Update:**
- `posthog/models/integration.py`

**Changes Needed:**
1. Update `GoogleCloudIntegration.integration_from_key` to detect and handle external_account configs
2. Update `refresh_access_token()` to handle external account credential refresh
3. Add validation for external_account configurations

## Testing

### Unit Tests Needed

1. **`posthog/google_cloud_auth.py`**:
   - Test service account credential creation
   - Test external account credential creation
   - Test project ID extraction from various config formats
   - Test error handling for invalid configs

2. **BigQuery Source**:
   - Test with service account key (existing tests should pass)
   - Test with Workload Identity Federation config
   - Test credential validation with both auth types
   - Test backwards compatibility

3. **Integration Tests**:
   - End-to-end BigQuery data import with Workload Identity
   - Batch export with Workload Identity
   - Token refresh behavior

### Manual Testing Checklist

- [ ] Upload service account key JSON - should work as before
- [ ] Upload Workload Identity Federation JSON - should authenticate successfully
- [ ] Verify BigQuery table listing works
- [ ] Verify data import completes successfully
- [ ] Verify batch export works (when implemented)
- [ ] Test with different GCP projects (cross-project access)
- [ ] Test error messages for invalid credentials

## Security Considerations

1. **Token Lifetime**: External account credentials generate short-lived tokens (typically 1 hour). The google-auth library handles automatic refresh.

2. **Credential Storage**: External account configs should be stored in `sensitive_config` field of Integration model (encrypted).

3. **Permissions**: Workload Identity Federation requires careful IAM configuration. Document required roles clearly.

4. **Validation**: Always validate credentials before storing to prevent misconfigured integrations.

## Documentation Updates Needed

1. **User Documentation**:
   - Add guide on setting up Workload Identity Federation for PostHog
   - Include step-by-step GCP configuration
   - Add troubleshooting section

2. **Developer Documentation**:
   - Document the `google_cloud_auth` module API
   - Add examples for each Google Cloud service
   - Update contribution guide for adding new Google Cloud integrations

## Migration Path

### For Existing Users

No migration needed! Existing service account key configurations continue to work without any changes.

### For New Users

Users can choose between:
1. **Service Account Keys** (traditional, simpler setup)
2. **Workload Identity Federation** (more secure, recommended for production)

## References

- [Workload Identity Federation](https://cloud.google.com/iam/docs/workload-identity-federation)
- [Cloud SQL IAM Authentication](https://cloud.google.com/sql/docs/postgres/iam-authentication)
- [google-auth-library-python](https://googleapis.dev/python/google-auth/latest/user-guide.html)
- [External Account Credentials](https://google-auth.readthedocs.io/en/latest/reference/google.auth.external_account.html)
