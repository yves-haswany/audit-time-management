"""Password hashing and token generation."""
import secrets
from passlib.context import CryptContext

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd.verify(plain, hashed)


def generate_token() -> str:
    return secrets.token_hex(16)