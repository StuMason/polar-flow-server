"""Security utilities for token encryption."""

from cryptography.fernet import Fernet

from polar_flow_server.core.config import settings


class TokenEncryption:
    """Encrypt and decrypt OAuth tokens for secure storage."""

    def __init__(self) -> None:
        """Initialize encryption with key from settings."""
        key = settings.get_encryption_key()
        self.cipher = Fernet(key)

    def encrypt(self, token: str) -> str:
        """Encrypt a token for database storage.

        Args:
            token: Plain text token

        Returns:
            Encrypted token (base64 encoded)
        """
        return self.cipher.encrypt(token.encode()).decode()

    def decrypt(self, encrypted_token: str) -> str:
        """Decrypt a token from database.

        Args:
            encrypted_token: Encrypted token (base64 encoded)

        Returns:
            Plain text token
        """
        return self.cipher.decrypt(encrypted_token.encode()).decode()


# Global instance
token_encryption = TokenEncryption()
