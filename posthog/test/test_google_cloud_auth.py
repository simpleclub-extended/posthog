"""Tests for Google Cloud authentication utilities."""

import pytest
from unittest.mock import Mock, patch

from posthog.google_cloud_auth import get_google_credentials, get_project_id_from_credentials


class TestGoogleCloudAuth:
    """Test Google Cloud authentication helper functions."""

    def test_get_google_credentials_service_account(self):
        """Test creating credentials from service account key."""
        sa_config = {
            "type": "service_account",
            "project_id": "test-project",
            "private_key": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----",
            "private_key_id": "key123",
            "client_email": "test@test-project.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token",
        }

        with patch("posthog.google_cloud_auth.service_account.Credentials.from_service_account_info") as mock_creds:
            mock_creds_instance = Mock()
            mock_creds_instance.project_id = "test-project"
            mock_creds.return_value = mock_creds_instance

            credentials = get_google_credentials(sa_config, ["https://www.googleapis.com/auth/cloud-platform"])

            assert credentials == mock_creds_instance
            mock_creds.assert_called_once()
            call_args = mock_creds.call_args
            assert call_args[0][0]["project_id"] == "test-project"
            assert call_args[0][0]["client_email"] == "test@test-project.iam.gserviceaccount.com"
            assert call_args[1]["scopes"] == ["https://www.googleapis.com/auth/cloud-platform"]

    def test_get_google_credentials_legacy_format(self):
        """Test creating credentials from legacy format (no type field)."""
        legacy_config = {
            "project_id": "test-project",
            "private_key": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----",
            "private_key_id": "key123",
            "client_email": "test@test-project.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token",
        }

        with patch("posthog.google_cloud_auth.service_account.Credentials.from_service_account_info") as mock_creds:
            mock_creds_instance = Mock()
            mock_creds.return_value = mock_creds_instance

            credentials = get_google_credentials(legacy_config, ["https://www.googleapis.com/auth/cloud-platform"])

            assert credentials == mock_creds_instance

    def test_get_google_credentials_external_account(self):
        """Test creating credentials from Workload Identity Federation config."""
        external_config = {
            "type": "external_account",
            "audience": "//iam.googleapis.com/projects/123/locations/global/workloadIdentityPools/pool/providers/provider",
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "token_url": "https://sts.googleapis.com/v1/token",
            "credential_source": {"file": "/var/run/secrets/token"},
            "service_account_impersonation_url": "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/sa@project.iam.gserviceaccount.com:generateAccessToken",
        }

        with patch("posthog.google_cloud_auth.external_account.Credentials.from_info") as mock_creds:
            mock_creds_instance = Mock()
            mock_creds.return_value = mock_creds_instance

            credentials = get_google_credentials(external_config, ["https://www.googleapis.com/auth/cloud-platform"])

            assert credentials == mock_creds_instance
            mock_creds.assert_called_once_with(external_config, scopes=["https://www.googleapis.com/auth/cloud-platform"])

    def test_get_google_credentials_invalid_config(self):
        """Test error handling for invalid config."""
        invalid_config = {"some": "invalid", "config": "here"}

        with pytest.raises(ValueError, match="Invalid auth_config"):
            get_google_credentials(invalid_config, ["https://www.googleapis.com/auth/cloud-platform"])

    def test_get_google_credentials_missing_fields(self):
        """Test error handling for missing required fields."""
        incomplete_config = {
            "type": "service_account",
            "project_id": "test-project",
            # Missing other required fields
        }

        with pytest.raises(ValueError, match="Missing required service account fields"):
            get_google_credentials(incomplete_config, ["https://www.googleapis.com/auth/cloud-platform"])

    def test_get_project_id_from_credentials_service_account(self):
        """Test extracting project ID from service account credentials."""
        mock_credentials = Mock()
        mock_credentials.project_id = "test-project"

        auth_config = {"project_id": "test-project"}

        project_id = get_project_id_from_credentials(mock_credentials, auth_config)

        assert project_id == "test-project"

    def test_get_project_id_from_config(self):
        """Test extracting project ID from config when not in credentials."""
        mock_credentials = Mock()
        del mock_credentials.project_id  # Simulate credentials without project_id

        auth_config = {"project_id": "test-project"}

        project_id = get_project_id_from_credentials(mock_credentials, auth_config)

        assert project_id == "test-project"

    def test_get_project_id_from_external_account_impersonation_url(self):
        """Test extracting project ID from external account impersonation URL."""
        mock_credentials = Mock()
        del mock_credentials.project_id

        auth_config = {
            "type": "external_account",
            "service_account_impersonation_url": "https://iamcredentials.googleapis.com/v1/projects/my-project/serviceAccounts/sa@project.iam.gserviceaccount.com:generateAccessToken",
        }

        project_id = get_project_id_from_credentials(mock_credentials, auth_config)

        assert project_id == "my-project"

    def test_get_project_id_no_source(self):
        """Test error when project ID cannot be determined."""
        mock_credentials = Mock()
        del mock_credentials.project_id

        auth_config = {"type": "external_account"}  # No project_id anywhere

        with pytest.raises(ValueError, match="Could not determine project_id"):
            get_project_id_from_credentials(mock_credentials, auth_config)
