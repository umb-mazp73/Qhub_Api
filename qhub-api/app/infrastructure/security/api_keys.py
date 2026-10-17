import hashlib
import secrets


def hashear_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generar_api_key() -> str:
    return secrets.token_urlsafe(32)


class ApiKeyCodec:
    def generate(self) -> str:
        return generar_api_key()

    def digest(self, plain: str) -> str:
        return hashear_api_key(plain)
