#!/usr/bin/env python3
"""Generate a SHA-256 hex hash for the auth.js password.

Usage:
    .venv/bin/python scripts/generate_password_hash.py
    .venv/bin/python scripts/generate_password_hash.py mysecret
"""
import hashlib
import sys

password = sys.argv[1] if len(sys.argv) > 1 else input("Password: ")
print(hashlib.sha256(password.encode("utf-8")).hexdigest())
