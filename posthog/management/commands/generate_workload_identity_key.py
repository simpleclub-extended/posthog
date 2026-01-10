"""
Management command to generate and rotate RSA keys for Workload Identity Federation.

Usage:
    python manage.py generate_workload_identity_key

This command generates a new RSA key pair for signing Workload Identity Federation
JWT tokens. The private key is used to sign tokens, and the public key is exposed
via the JWKS endpoint for Google Cloud to validate the tokens.
"""

import base64
import uuid
from datetime import timedelta

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.management.base import BaseCommand
from django.utils import timezone

from posthog.models.workload_identity_key import WorkloadIdentityKey


class Command(BaseCommand):
    help = "Generate a new RSA key pair for Workload Identity Federation JWT signing"

    def add_arguments(self, parser):
        parser.add_argument(
            "--key-size",
            type=int,
            default=2048,
            help="RSA key size in bits (default: 2048)",
        )
        parser.add_argument(
            "--validity-days",
            type=int,
            default=365,
            help="Number of days the key should be valid (default: 365)",
        )
        parser.add_argument(
            "--deactivate-old",
            action="store_true",
            help="Deactivate all previously active keys",
        )

    def handle(self, *args, **options):
        key_size = options["key_size"]
        validity_days = options["validity_days"]
        deactivate_old = options["deactivate_old"]

        self.stdout.write(f"Generating {key_size}-bit RSA key pair...")

        # Generate RSA key pair
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
            backend=default_backend()
        )
        public_key = private_key.public_key()

        # Serialize private key to PEM format
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode('utf-8')

        # Serialize public key to PEM format
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

        # Extract modulus (n) and exponent (e) for JWKS
        public_numbers = public_key.public_numbers()
        
        # Convert to base64url encoding (without padding)
        def int_to_base64url(num):
            # Convert integer to bytes
            byte_length = (num.bit_length() + 7) // 8
            num_bytes = num.to_bytes(byte_length, byteorder='big')
            # Base64url encode without padding
            return base64.urlsafe_b64encode(num_bytes).rstrip(b'=').decode('utf-8')
        
        n = int_to_base64url(public_numbers.n)
        e = int_to_base64url(public_numbers.e)

        # Generate a unique key ID
        key_id = f"posthog-workload-identity-{uuid.uuid4().hex[:12]}"

        # Calculate expiration date
        expires_at = timezone.now() + timedelta(days=validity_days)

        # Deactivate old keys if requested
        if deactivate_old:
            old_keys = WorkloadIdentityKey.objects.filter(is_active=True)
            count = old_keys.update(is_active=False)
            if count > 0:
                self.stdout.write(self.style.WARNING(f"Deactivated {count} old key(s)"))

        # Create the new key
        key_model = WorkloadIdentityKey.objects.create(
            key_id=key_id,
            private_key=private_pem,
            public_key=public_pem,
            public_key_n=n,
            public_key_e=e,
            algorithm="RS256",
            is_active=True,
            expires_at=expires_at,
        )

        self.stdout.write(self.style.SUCCESS(f"Successfully created new key: {key_id}"))
        self.stdout.write(f"  Algorithm: RS256")
        self.stdout.write(f"  Key Size: {key_size} bits")
        self.stdout.write(f"  Expires: {expires_at}")
        self.stdout.write(f"  Active: {key_model.is_active}")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Key is ready for use"))
        self.stdout.write("Public key will be available at: /.well-known/jwks.json")
