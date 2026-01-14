"""
Unit tests for Workload Identity Federation implementation.
"""

import time
from unittest.mock import Mock, patch, MagicMock
from datetime import timedelta

import jwt
import pytest
from django.utils import timezone
from django.test import TestCase

from posthog.models import Team, Organization, User
from posthog.models.workload_identity_key import WorkloadIdentityKey
from posthog.models.workload_identity_config import WorkloadIdentityConfig
from posthog.api.workload_identity import (
    generate_workload_identity_token,
    get_workload_identity_issuer,
    _get_project_region,
)


class TestWorkloadIdentityToken(TestCase):
    """Test JWT token generation for Workload Identity Federation."""
    
    def setUp(self):
        """Set up test data."""
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(
            organization=self.organization,
            name="Test Team"
        )
        
        # Create a test RSA key
        self.key = WorkloadIdentityKey.objects.create(
            key_id="test-key-123",
            private_key="""-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC7VJTUt9Us8cKj
MzEfYyjiWA4R4/M2bS1+fWIcPm15j9kDXpb8eGQmU2E2kNvJJSfVqjZ2Ot3xHaRU
l5tU4PEQxJqZvSWFxZXECrLEPr+aMVECFU4rKCqU5qx5Y8k7J9LqQU1J9OV8eUxR
cB3YH5OuL3lYx0ItDXPh0DxJqjZ2Ot3xHaRUl5tU4PEQxJqZvSWFxZXECrLEPr+a
MVECFBUHdQeFd0fPEQxJqZvSWFxZXECrLEPr+aMVECFU4rKCqU5qx5Y8k7J9LqQU
1J9OV8eUxRcB3YH5OuL3lYx0ItDXPh0DxJAgMBAAECggEASkl5J4r8dPpBG...
-----END PRIVATE KEY-----""",
            public_key="""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAu1SU1LfVLPHCozMxH2Mo
4lgOEePzNm0tfn1iHD5teY/ZA16W/HhkJlNhNpDbyY...
-----END PUBLIC KEY-----""",
            public_key_n="test_n_value",
            public_key_e="AQAB",
            algorithm="RS256",
            is_active=True,
            expires_at=timezone.now() + timedelta(days=365),
        )
        
        self.audience = "//iam.googleapis.com/projects/123/locations/global/workloadIdentityPools/pool/providers/provider"
    
    def test_generate_token_success(self):
        """Test successful token generation."""
        token = generate_workload_identity_token(
            team_id=self.team.id,
            audience=self.audience,
            service_type="bigquery",
            service_id="source-123",
        )
        
        # Verify token is a string
        assert isinstance(token, str)
        
        # Decode token without verification to inspect claims
        decoded = jwt.decode(token, options={"verify_signature": False})
        
        # Verify claims
        assert decoded["organization_id"] == str(self.organization.id)
        assert decoded["project_id"] == str(self.team.id)
        assert decoded["project_name"] == self.team.name
        assert decoded["aud"] == self.audience
        assert decoded["service_type"] == "bigquery"
        assert decoded["service_id"] == "source-123"
        
        # Verify subject format
        expected_sub = f"project:{self.organization.id}/{self.team.id}:bigquery:source-123"
        assert decoded["sub"] == expected_sub
        
        # Verify issuer
        assert decoded["iss"] == get_workload_identity_issuer()
    
    def test_generate_token_without_service_info(self):
        """Test token generation without service type and ID."""
        token = generate_workload_identity_token(
            team_id=self.team.id,
            audience=self.audience,
        )
        
        decoded = jwt.decode(token, options={"verify_signature": False})
        
        # Service fields should not be present
        assert "service_type" not in decoded
        assert "service_id" not in decoded
        
        # Subject should be simpler
        expected_sub = f"project:{self.organization.id}/{self.team.id}"
        assert decoded["sub"] == expected_sub
    
    def test_generate_token_team_not_found(self):
        """Test token generation with non-existent team."""
        with pytest.raises(ValueError, match="Team with id 99999 does not exist"):
            generate_workload_identity_token(
                team_id=99999,
                audience=self.audience,
            )
    
    def test_generate_token_no_active_key(self):
        """Test token generation when no active key exists."""
        # Deactivate the key
        self.key.is_active = False
        self.key.save()
        
        with pytest.raises(ValueError, match="No active signing key available"):
            generate_workload_identity_token(
                team_id=self.team.id,
                audience=self.audience,
            )
    
    def test_token_expiration(self):
        """Test that token has correct expiration."""
        token = generate_workload_identity_token(
            team_id=self.team.id,
            audience=self.audience,
        )
        
        decoded = jwt.decode(token, options={"verify_signature": False})
        
        # Token should expire in ~1 hour
        exp = decoded["exp"]
        iat = decoded["iat"]
        
        assert exp - iat == 3600  # 1 hour
    
    def test_key_usage_tracking(self):
        """Test that key usage is tracked."""
        # Check initial state
        assert self.key.last_used_at is None
        
        # Generate token
        generate_workload_identity_token(
            team_id=self.team.id,
            audience=self.audience,
        )
        
        # Refresh from DB and check usage was tracked
        self.key.refresh_from_db()
        assert self.key.last_used_at is not None


class TestWorkloadIdentityKey(TestCase):
    """Test WorkloadIdentityKey model."""
    
    def test_get_active_key(self):
        """Test getting the active key."""
        # Create expired key
        expired_key = WorkloadIdentityKey.objects.create(
            key_id="expired-key",
            private_key="test",
            public_key="test",
            public_key_n="test",
            is_active=True,
            expires_at=timezone.now() - timedelta(days=1),
        )
        
        # Create active key
        active_key = WorkloadIdentityKey.objects.create(
            key_id="active-key",
            private_key="test",
            public_key="test",
            public_key_n="test",
            is_active=True,
            expires_at=timezone.now() + timedelta(days=365),
        )
        
        # Should return the active, non-expired key
        result = WorkloadIdentityKey.get_active_key()
        assert result.id == active_key.id
    
    def test_get_all_valid_keys(self):
        """Test getting all valid keys including grace period."""
        now = timezone.now()
        
        # Create keys with different expiration states
        expired_outside_grace = WorkloadIdentityKey.objects.create(
            key_id="expired-old",
            private_key="test",
            public_key="test",
            public_key_n="test",
            expires_at=now - timedelta(days=2),
        )
        
        expired_within_grace = WorkloadIdentityKey.objects.create(
            key_id="expired-recent",
            private_key="test",
            public_key="test",
            public_key_n="test",
            expires_at=now - timedelta(hours=12),
        )
        
        active_key = WorkloadIdentityKey.objects.create(
            key_id="active",
            private_key="test",
            public_key="test",
            public_key_n="test",
            expires_at=now + timedelta(days=365),
        )
        
        # Get all valid keys
        valid_keys = list(WorkloadIdentityKey.get_all_valid_keys())
        
        # Should include active and recently expired (within 24h grace)
        assert len(valid_keys) == 2
        key_ids = {k.key_id for k in valid_keys}
        assert "active" in key_ids
        assert "expired-recent" in key_ids
        assert "expired-old" not in key_ids


class TestWorkloadIdentityConfig(TestCase):
    """Test WorkloadIdentityConfig model."""
    
    def setUp(self):
        """Set up test data."""
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(
            organization=self.organization,
            name="Test Team"
        )
        self.user = User.objects.create(email="test@example.com")
    
    def test_create_config(self):
        """Test creating a Workload Identity configuration."""
        config = WorkloadIdentityConfig.objects.create(
            team=self.team,
            audience="//iam.googleapis.com/projects/123/...",
            google_cloud_project_id="test-project",
            is_enabled=True,
            created_by=self.user,
        )
        
        assert config.team == self.team
        assert config.is_enabled is True
    
    def test_get_for_team(self):
        """Test getting configuration for a team."""
        # No config exists
        assert WorkloadIdentityConfig.get_for_team(self.team.id) is None
        
        # Create disabled config
        disabled_config = WorkloadIdentityConfig.objects.create(
            team=self.team,
            audience="test",
            google_cloud_project_id="test",
            is_enabled=False,
        )
        
        # Should still return None (disabled)
        assert WorkloadIdentityConfig.get_for_team(self.team.id) is None
        
        # Enable config
        disabled_config.is_enabled = True
        disabled_config.save()
        
        # Should now return the config
        result = WorkloadIdentityConfig.get_for_team(self.team.id)
        assert result.id == disabled_config.id


class TestGoogleSTSClient(TestCase):
    """Test Google STS client for token exchange."""
    
    @patch('posthog.google_cloud_sts.requests.post')
    def test_exchange_token_success(self, mock_post):
        """Test successful token exchange."""
        from posthog.google_cloud_sts import GoogleSTSClient
        
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "ya29.test_token",
            "issued_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        mock_post.return_value = mock_response
        
        client = GoogleSTSClient()
        result = client.exchange_token(
            subject_token="test.jwt.token",
            audience="//iam.googleapis.com/test",
        )
        
        # Verify request
        assert mock_post.called
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://sts.googleapis.com/v1/token"
        
        request_body = call_args[1]["json"]
        assert request_body["subjectToken"] == "test.jwt.token"
        assert request_body["audience"] == "//iam.googleapis.com/test"
        
        # Verify response
        assert result["access_token"] == "ya29.test_token"
        assert result["token_type"] == "Bearer"
        assert result["expires_in"] == 3600
    
    @patch('posthog.google_cloud_sts.requests.post')
    def test_exchange_token_error(self, mock_post):
        """Test token exchange with error response."""
        from posthog.google_cloud_sts import GoogleSTSClient
        
        # Mock error response
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Invalid token"
        mock_response.raise_for_status.side_effect = Exception("HTTP 400")
        mock_post.return_value = mock_response
        
        client = GoogleSTSClient()
        
        with pytest.raises(Exception):
            client.exchange_token(
                subject_token="invalid.token",
                audience="//iam.googleapis.com/test",
            )


class TestAuthenticationHelpers(TestCase):
    """Test authentication helper functions."""
    
    def setUp(self):
        """Set up test data."""
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(
            organization=self.organization,
            name="Test Team"
        )
    
    @patch('posthog.google_cloud_helpers.get_google_cloud_access_token')
    def test_get_google_cloud_credentials(self, mock_get_token):
        """Test getting Google Cloud credentials."""
        from posthog.google_cloud_helpers import get_google_cloud_credentials
        
        mock_get_token.return_value = "ya29.test_access_token"
        
        credentials = get_google_cloud_credentials(
            team_id=self.team.id,
            audience="//iam.googleapis.com/test",
            service_type="bigquery",
        )
        
        assert credentials.token == "ya29.test_access_token"
        assert "https://www.googleapis.com/auth/cloud-platform" in credentials.scopes
    
    @patch('posthog.google_cloud_helpers.get_google_cloud_credentials')
    @patch('posthog.google_cloud_helpers.bigquery.Client')
    def test_bigquery_client_context_manager(self, mock_bq_client, mock_get_creds):
        """Test BigQuery client context manager."""
        from posthog.google_cloud_helpers import bigquery_client_with_workload_identity
        
        mock_creds = Mock()
        mock_get_creds.return_value = mock_creds
        
        mock_client_instance = Mock()
        mock_bq_client.return_value = mock_client_instance
        
        with bigquery_client_with_workload_identity(
            team_id=self.team.id,
            audience="//iam.googleapis.com/test",
            project_id="test-project",
        ) as client:
            # Verify client was created with correct parameters
            mock_bq_client.assert_called_once_with(
                project="test-project",
                credentials=mock_creds,
            )
            
            # Verify we get the client instance
            assert client == mock_client_instance
        
        # Verify client was closed
        mock_client_instance.close.assert_called_once()
