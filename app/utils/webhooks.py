import secrets
from werkzeug.security import check_password_hash, generate_password_hash


def hash_webhook_secret(secret: str) -> str:
	"""Hash a webhook secret for storage."""
	return generate_password_hash(secret, method='pbkdf2:sha256')


def verify_webhook_secret(secret: str, secret_hash: str) -> bool:
	"""Check a plaintext secret against the stored hash."""
	if not secret_hash:
		return False
	return check_password_hash(secret_hash, secret)


def generate_webhook_secret() -> str:
	"""Generate a random webhook secret suitable for API clients."""
	return secrets.token_hex(32)
