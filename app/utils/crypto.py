"""
Symmetric encryption for sensitive database fields (e.g. relay passwords).

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the cryptography package.
The encryption key is derived from the ENCRYPTION_KEY env var, or falls back
to JWT_SECRET (already required for the app to run).

Usage:
    from app.utils.crypto import encrypt_field, decrypt_field

    encrypted = encrypt_field('my-secret-password')
    # Store `encrypted` in the database

    plaintext = decrypt_field(encrypted)
    # Returns 'my-secret-password'
"""

import base64
import logging
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

_fernet = None


def _get_fernet() -> Fernet:
	"""Get or create the Fernet instance, deriving the key from env vars."""
	global _fernet
	if _fernet is not None:
		return _fernet

	# Use ENCRYPTION_KEY if set, otherwise derive from JWT_SECRET
	key_material = os.environ.get('ENCRYPTION_KEY', '').strip()
	if not key_material:
		key_material = os.environ.get('JWT_SECRET', '').strip()
	if not key_material:
		raise RuntimeError(
			"ENCRYPTION_KEY or JWT_SECRET environment variable is required "
			"for encrypting sensitive database fields"
		)

	# Derive a 32-byte Fernet key from the key material using PBKDF2
	# Use a fixed salt — this is acceptable here because the key material
	# is already a high-entropy secret (JWT_SECRET or ENCRYPTION_KEY).
	# The salt just ensures domain separation from other uses of the same secret.
	salt = b'py_pg_email_field_encryption_v1'
	kdf = PBKDF2HMAC(
		algorithm=hashes.SHA256(),
		length=32,
		salt=salt,
		iterations=100_000,
	)
	key = base64.urlsafe_b64encode(kdf.derive(key_material.encode('utf-8')))
	_fernet = Fernet(key)
	return _fernet


def encrypt_field(plaintext: str) -> str:
	"""Encrypt a string for storage in the database.

	Returns a URL-safe base64-encoded Fernet token.
	"""
	if not plaintext:
		return ''
	f = _get_fernet()
	return f.encrypt(plaintext.encode('utf-8')).decode('utf-8')


def decrypt_field(ciphertext: str) -> str:
	"""Decrypt a Fernet token from the database.

	Returns the original plaintext string.
	Raises cryptography.fernet.InvalidToken if the value is a Fernet
	token but the key is wrong or the value has been tampered with.
	"""
	if not ciphertext:
		return ''
	# Legacy plaintext fallback: relay_password_encrypted may contain
	# bare plaintext for rows populated by db/outbound_migration.sql
	# before Fernet enforcement. Once those rows are rotated through
	# the /api/domains/<domain>/relay endpoint they get re-stored as
	# Fernet tokens and this branch stops triggering.
	if not is_encrypted(ciphertext):
		return ciphertext
	f = _get_fernet()
	return f.decrypt(ciphertext.encode('utf-8')).decode('utf-8')


def is_encrypted(value: str) -> bool:
	"""Check if a value looks like a Fernet token (vs plaintext).

	Fernet tokens are URL-safe base64 and start with 'gAAAAA'.
	"""
	if not value:
		return False
	return value.startswith('gAAAAA')
