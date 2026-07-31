"""Security utilities for token encryption."""

import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.config import settings

logger = logging.getLogger(__name__)


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


async def verify_stored_tokens_decryptable(session: AsyncSession) -> bool:
    """Check that stored Polar tokens decrypt with the current encryption key.

    Called at startup. If the key has changed (e.g. a redeploy regenerated it
    because the key directory was not persisted), every stored token is
    unreadable and each Polar account must re-authorize — say so loudly
    instead of failing silently at the next sync.

    Returns True if tokens are healthy (or none are stored), False on mismatch.
    """
    from polar_flow_server.models.user import User

    result = await session.execute(select(User.access_token_encrypted).limit(5))
    healthy = True
    for (encrypted,) in result:
        if encrypted is None:
            continue
        try:
            token_encryption.decrypt(encrypted)
        except (InvalidToken, ValueError):
            healthy = False
            break
    if not healthy:
        logger.critical(
            "ENCRYPTION KEY MISMATCH: stored Polar tokens cannot be decrypted with the "
            "current encryption key. This usually means the key file was lost in a "
            "redeploy (key directory not on a persistent volume) and a new key was "
            "generated. Every connected Polar account must re-authorize via the admin "
            "panel. To prevent recurrence, persist the key directory or set "
            "ENCRYPTION_KEY explicitly."
        )
    return healthy
