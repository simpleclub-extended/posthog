"""
Model for storing RSA key pairs used to sign Workload Identity Federation JWT tokens.

These keys are used by PostHog to act as an OIDC identity provider for Google Cloud.
"""

from django.db import models
from django.utils import timezone


class WorkloadIdentityKey(models.Model):
    """
    RSA key pair for signing Workload Identity Federation JWT tokens.
    
    PostHog acts as an OIDC identity provider and signs JWT tokens with these keys.
    Google Cloud validates the tokens using the public key exposed via the JWKS endpoint.
    """
    
    # Unique identifier for this key (used as 'kid' in JWT header)
    key_id = models.CharField(max_length=255, unique=True, db_index=True)
    
    # RSA private key (PEM format) - used to sign tokens
    # This should be encrypted at rest
    private_key = models.TextField()
    
    # RSA public key (PEM format) - exposed via JWKS endpoint
    public_key = models.TextField()
    
    # RSA modulus (n) for JWKS - base64url encoded
    public_key_n = models.TextField()
    
    # RSA exponent (e) for JWKS - base64url encoded (usually "AQAB")
    public_key_e = models.TextField(default="AQAB")
    
    # Algorithm used for signing (always RS256 for Workload Identity)
    algorithm = models.CharField(max_length=10, default="RS256")
    
    # Whether this key is currently active for signing new tokens
    is_active = models.BooleanField(default=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    # Last time this key was used to sign a token
    last_used_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_active", "expires_at"]),
        ]
    
    def __str__(self):
        return f"WorkloadIdentityKey({self.key_id}, active={self.is_active})"
    
    @classmethod
    def get_active_key(cls):
        """Get the current active key for signing tokens."""
        return cls.objects.filter(
            is_active=True,
            expires_at__gt=timezone.now()
        ).first()
    
    @classmethod
    def get_all_valid_keys(cls):
        """Get all valid keys for JWKS endpoint (includes recently expired for grace period)."""
        # Include keys that haven't expired or expired less than 24 hours ago
        grace_period = timezone.now() - timezone.timedelta(hours=24)
        return cls.objects.filter(
            models.Q(expires_at__gt=grace_period) | models.Q(expires_at__isnull=True)
        ).order_by("-created_at")
    
    def mark_used(self):
        """Update the last_used_at timestamp."""
        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at"])
