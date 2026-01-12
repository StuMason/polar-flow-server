"""Password hashing utilities using Argon2."""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Create password hasher with secure defaults
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password using Argon2.

    Args:
        password: Plain text password

    Returns:
        Hashed password string
    """
    return _hasher.hash(password)


def verify_password(password: str, hash: str) -> bool:
    """Verify a password against its hash.

    Args:
        password: Plain text password to verify
        hash: Stored password hash

    Returns:
        True if password matches, False otherwise
    """
    try:
        _hasher.verify(hash, password)
        return True
    except VerifyMismatchError:
        return False
