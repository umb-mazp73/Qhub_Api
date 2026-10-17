import asyncio

import bcrypt

from app.application.errors import CryptoFailure

_BCRYPT_ROUNDS = 12


def bcrypt_hash_sync(plain: str) -> str:
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def bcrypt_verify_sync(plain: str, encoded: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), encoded.encode("utf-8"))
    except ValueError:
        return False


class BcryptPasswordHasher:
    async def hash_password(self, plain: str) -> str:
        try:
            return await asyncio.to_thread(bcrypt_hash_sync, plain)
        except Exception as exc:
            raise CryptoFailure(operation="password_hash") from exc

    async def verify_password(self, plain: str, encoded: str) -> bool:
        try:
            return await asyncio.to_thread(bcrypt_verify_sync, plain, encoded)
        except Exception as exc:
            raise CryptoFailure(operation="password_verify") from exc
