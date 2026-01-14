# Workload Identity Federation Integration Guide

This document provides a comprehensive guide for integrating Google Cloud services with PostHog using Workload Identity Federation.

## Overview

PostHog now supports Workload Identity Federation for Google Cloud services, eliminating the need for static service account keys. This provides:
- **Enhanced Security**: Short-lived tokens instead of long-lived keys
- **Organization Isolation**: Attribute-based access control prevents cross-organization data access
- **Simplified Management**: No key rotation or storage concerns
- **Audit Trail**: Complete logging of token generation and usage

## Architecture

```
PostHog Service
    ↓
generate_workload_identity_token()
    ↓
JWT Token (OIDC)
    ↓
Google STS API
    ↓
Access Token
    ↓
Google Cloud Services (BigQuery, Storage, PubSub, etc.)
```

## Implementation Status

### ✅ Completed
- OIDC provider infrastructure (discovery and JWKS endpoints)
- JWT token generation with organization/project claims
- Google STS token exchange client
- RSA key management and rotation
- Authentication helpers for BigQuery and Cloud Storage
- Configuration models for teams
- Comprehensive unit tests
- Testing guide and documentation

### 🔄 In Progress
- Database migrations
- Integration documentation

### ⏳ Pending
- BigQuery data source integration
- BigQuery batch export integration
- Google Cloud Storage batch export
- Google PubSub integration
- Cloud SQL IAM authentication
- UI for configuration
- End-to-end tests

## How to Integrate a Google Cloud Service

### Step 1: Get Workload Identity Configuration

```python
from posthog.models.workload_identity_config import WorkloadIdentityConfig

# Get configuration for a team
config = WorkloadIdentityConfig.get_for_team(team_id)

if config is None:
    # Team hasn't configured Workload Identity
    # Fall back to service account keys
    pass
```

### Step 2: Use Authentication Helpers

#### For BigQuery:

```python
from posthog.google_cloud_helpers import bigquery_client_with_workload_identity

# Use the context manager
with bigquery_client_with_workload_identity(
    team_id=team.id,
    audience=config.audience,
    project_id=config.google_cloud_project_id,
    service_type="bigquery_source",
    service_id=str(source_id),
) as client:
    # Use BigQuery client
    query_job = client.query("SELECT * FROM dataset.table")
    results = query_job.result()
```

#### For Cloud Storage:

```python
from posthog.google_cloud_helpers import storage_client_with_workload_identity

with storage_client_with_workload_identity(
    team_id=team.id,
    audience=config.audience,
    project_id=config.google_cloud_project_id,
    service_type="storage_export",
    service_id=str(export_id),
) as client:
    # Use Cloud Storage client
    bucket = client.bucket("my-bucket")
    blob = bucket.blob("data.json")
    blob.upload_from_string(data)
```

#### Custom Service:

```python
from posthog.google_cloud_helpers import get_google_cloud_credentials

credentials = get_google_cloud_credentials(
    team_id=team.id,
    audience=config.audience,
    service_type="custom_service",
    service_id="service-123",
    scopes=["https://www.googleapis.com/auth/custom-scope"],
)

# Use credentials with any Google Cloud client
from google.cloud import some_service
client = some_service.Client(credentials=credentials)
```

### Step 3: Handle Errors

```python
from posthog.models.workload_identity_config import WorkloadIdentityConfig
from posthog.google_cloud_helpers import bigquery_client_with_workload_identity
import structlog

logger = structlog.get_logger(__name__)

def fetch_bigquery_data(team_id: int, query: str):
    """Fetch data from BigQuery using Workload Identity if configured."""
    
    # Check if team has Workload Identity configured
    config = WorkloadIdentityConfig.get_for_team(team_id)
    
    if config is None:
        logger.info("workload_identity_not_configured", team_id=team_id)
        # Fall back to service account key authentication
        return fetch_with_service_account(team_id, query)
    
    try:
        with bigquery_client_with_workload_identity(
            team_id=team_id,
            audience=config.audience,
            project_id=config.google_cloud_project_id,
            service_type="bigquery_source",
            service_id="default",
        ) as client:
            query_job = client.query(query)
            return list(query_job.result())
            
    except ValueError as e:
        logger.error("workload_identity_error", error=str(e), team_id=team_id)
        # Handle specific errors (no active key, team not found, etc.)
        raise
        
    except Exception as e:
        logger.error("bigquery_query_failed", error=str(e), team_id=team_id)
        raise
```

## Example: BigQuery Data Source Integration

Here's a complete example of integrating Workload Identity into a BigQuery data source:

```python
from contextlib import contextmanager
from typing import Iterator
from google.cloud import bigquery
from posthog.models import Team
from posthog.models.workload_identity_config import WorkloadIdentityConfig
from posthog.google_cloud_helpers import bigquery_client_with_workload_identity
import structlog

logger = structlog.get_logger(__name__)


@contextmanager
def get_bigquery_client(
    team: Team,
    service_account_key: dict | None = None,
    source_id: str | None = None,
) -> Iterator[bigquery.Client]:
    """
    Get a BigQuery client using Workload Identity if configured,
    otherwise fall back to service account key.
    
    Args:
        team: PostHog team
        service_account_key: Legacy service account key (optional)
        source_id: ID of the data source
        
    Yields:
        Authenticated BigQuery client
    """
    # Try Workload Identity first
    config = WorkloadIdentityConfig.get_for_team(team.id)
    
    if config is not None:
        logger.info(
            "using_workload_identity",
            team_id=team.id,
            project_id=config.google_cloud_project_id,
        )
        
        with bigquery_client_with_workload_identity(
            team_id=team.id,
            audience=config.audience,
            project_id=config.google_cloud_project_id,
            service_type="bigquery_source",
            service_id=source_id or "default",
        ) as client:
            yield client
            return
    
    # Fall back to service account key
    if service_account_key is None:
        raise ValueError("No Workload Identity configured and no service account key provided")
    
    logger.info("using_service_account_key", team_id=team.id)
    
    from google.oauth2 import service_account
    credentials = service_account.Credentials.from_service_account_info(
        service_account_key
    )
    
    client = bigquery.Client(
        project=service_account_key.get("project_id"),
        credentials=credentials,
    )
    
    try:
        yield client
    finally:
        client.close()


# Usage in data source
def sync_bigquery_source(team: Team, source_config: dict):
    """Sync data from BigQuery source."""
    
    with get_bigquery_client(
        team=team,
        service_account_key=source_config.get("service_account_key"),
        source_id=source_config.get("id"),
    ) as client:
        # Use BigQuery client
        dataset_id = source_config["dataset_id"]
        table_id = source_config["table_id"]
        
        query = f"""
            SELECT * FROM `{dataset_id}.{table_id}`
            WHERE created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
        """
        
        query_job = client.query(query)
        
        for row in query_job.result():
            # Process row
            process_row(row)
```

## Security Considerations

### 1. Org

anization Isolation

Tokens contain `organization_id` and `project_id` claims. Customers configure attribute conditions in Google Cloud:

```
assertion.organization_id == 'YOUR_ORG_ID' && assertion.project_id == 'YOUR_PROJECT_ID'
```

This ensures PostHog organization A cannot access Google Cloud resources of organization B.

### 2. Service Identification

Tokens include `service_type` and `service_id` for audit trails:
- `service_type`: bigquery, storage, pubsub, etc.
- `service_id`: Specific source/destination ID

### 3. Token Expiration

Tokens expire after 1 hour. The system automatically generates new tokens as needed.

### 4. Key Rotation

RSA keys can be rotated using:

```bash
python manage.py generate_workload_identity_key --deactivate-old
```

Old tokens remain valid during the 24-hour grace period.

## Monitoring

Monitor token generation and usage:

```bash
# Token generation
grep "workload_identity_token_generated" /var/log/posthog.log

# STS token exchange
grep "google_sts_token_exchange" /var/log/posthog.log

# Authentication failures
grep "workload_identity_error" /var/log/posthog.log
```

## Migration from Service Account Keys

For existing integrations:

1. **Keep service account key support** for backwards compatibility
2. **Add Workload Identity check** at the beginning of authentication flow
3. **Fall back to service account key** if Workload Identity not configured
4. **Provide migration guide** for customers to set up Workload Identity

Example migration pattern:

```python
def authenticate_google_cloud(team: Team, legacy_key: dict | None = None):
    # Try Workload Identity first
    config = WorkloadIdentityConfig.get_for_team(team.id)
    if config:
        return use_workload_identity(team, config)
    
    # Fall back to legacy method
    if legacy_key:
        return use_service_account_key(legacy_key)
    
    raise ValueError("No authentication method configured")
```

## Next Steps

1. **Implement migrations**: Run `python manage.py migrate` to create tables
2. **Generate keys**: Run `python manage.py generate_workload_identity_key`
3. **Configure Google Cloud**: Set up Workload Identity Pool (see WORKLOAD_IDENTITY_TESTING.md)
4. **Integrate services**: Start with BigQuery, then Cloud Storage, PubSub
5. **Add UI**: Create configuration interface for teams
6. **Test**: Use testing guide to validate end-to-end flow
7. **Document**: Update user-facing documentation
8. **Monitor**: Set up logging and alerting

## References

- [Testing Guide](./WORKLOAD_IDENTITY_TESTING.md)
- [Google Cloud Workload Identity Documentation](https://cloud.google.com/iam/docs/workload-identity-federation)
- [Unit Tests](./posthog/api/test/test_workload_identity.py)
