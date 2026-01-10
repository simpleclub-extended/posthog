# Workload Identity Federation Implementation - PR Summary

## Overview

This PR implements support for **Google Cloud Workload Identity Federation** across PostHog's Google Cloud integrations, addressing issue #41220. This allows PostHog to authenticate with Google Cloud services using short-lived tokens instead of static service account keys, significantly improving security.

## What's Implemented

### ✅ Core Infrastructure
- **`posthog/google_cloud_auth.py`**: Central authentication module that handles both:
  - Traditional service account JSON keys
  - Workload Identity Federation (external_account credentials)
  
### ✅ BigQuery Data Import
- Full support for Workload Identity Federation in BigQuery data source
- Updated all BigQuery helper functions and client managers
- Modified UI to accept both authentication types
- Maintains 100% backwards compatibility with existing configurations

### ✅ Integration Model
- Updated `GoogleCloudIntegration` class to support Workload Identity Federation
- Automatic credential refresh for both auth types
- Smart integration ID extraction from external accounts

### ✅ Tests & Documentation
- Comprehensive unit tests for authentication utilities
- Detailed setup guide in `WORKLOAD_IDENTITY_FEDERATION.md`
- Implementation patterns for remaining services

## What's Not Implemented (Yet)

The following components are **documented but not implemented** in this PR:
- BigQuery batch exports
- Google Cloud Storage (batch exports and CDP templates)
- Google PubSub (CDP templates)
- Cloud SQL IAM authentication for Postgres

See `WORKLOAD_IDENTITY_FEDERATION.md` for implementation guidance.

## How It Works

### Service Account Keys (Traditional - Still Supported)
```json
{
  "type": "service_account",
  "project_id": "my-project",
  "private_key": "-----BEGIN PRIVATE KEY-----...",
  "client_email": "service-account@my-project.iam.gserviceaccount.com",
  ...
}
```

### Workload Identity Federation (New)
```json
{
  "type": "external_account",
  "audience": "//iam.googleapis.com/projects/.../workloadIdentityPools/.../providers/...",
  "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
  "token_url": "https://sts.googleapis.com/v1/token",
  "credential_source": {
    "file": "/var/run/secrets/tokens/gcp-ksa/token"
  },
  "service_account_impersonation_url": "https://iamcredentials.googleapis.com/v1/..."
}
```

The authentication module automatically detects the type and handles both transparently.

## Key Features

1. **Backwards Compatible**: All existing service account key configurations continue to work without changes
2. **Transparent**: Users just upload a JSON file - the system handles the rest
3. **Secure**: Supports modern authentication patterns with short-lived tokens
4. **Extensible**: Easy to add support to other Google Cloud integrations

## Files Changed

### Core
- `posthog/google_cloud_auth.py` (new)
- `posthog/models/integration.py`

### BigQuery
- `posthog/temporal/data_imports/sources/bigquery/bigquery.py`
- `posthog/temporal/data_imports/sources/bigquery/source.py`

### Tests & Docs
- `posthog/test/test_google_cloud_auth.py` (new)
- `WORKLOAD_IDENTITY_FEDERATION.md` (new)

## Testing

### Unit Tests
```bash
pytest posthog/test/test_google_cloud_auth.py
```

### Integration Testing
1. Upload a Workload Identity Federation config to BigQuery source
2. Verify credential validation succeeds
3. Verify data import works
4. Verify token refresh works

See `WORKLOAD_IDENTITY_FEDERATION.md` for detailed testing checklist.

## Migration Path

### For Existing Users
No action required! Existing configurations continue to work.

### For New Users
Users can choose between:
- Service Account Keys (simpler setup)
- Workload Identity Federation (more secure, recommended for production)

## Security Considerations

- External account credentials are stored in encrypted `sensitive_config` field
- Tokens are automatically refreshed before expiration
- All credential validation happens before storage
- No long-lived secrets stored when using Workload Identity Federation

## Next Steps

To complete Workload Identity Federation support across all Google Cloud integrations:

1. Apply similar changes to BigQuery batch exports
2. Update GCS batch exports and CDP templates
3. Update Google PubSub CDP templates
4. Implement Cloud SQL IAM authentication

Patterns and examples are documented in `WORKLOAD_IDENTITY_FEDERATION.md`.

## References

- [Google Cloud Workload Identity Federation](https://cloud.google.com/iam/docs/workload-identity-federation)
- [External Account Credentials](https://google-auth.readthedocs.io/en/latest/reference/google.auth.external_account.html)
- [Cloud SQL IAM Authentication](https://cloud.google.com/sql/docs/postgres/iam-authentication)
- Issue: https://github.com/PostHog/posthog/issues/41220
