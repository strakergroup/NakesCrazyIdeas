import hashlib
import os
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

# Freeze the running build's identity at process import, not at each request.
# Deployments must restart API and workers together when code or libraries change.
_MODULES = [
    "checkers.py",
    "extraction.py",
    "providers.py",
    "rubric.py",
    "schemas.py",
    "service.py",
    "settings.py",
]
_BUILD_HASH = hashlib.sha256(b"".join((Path(__file__).parent / p).read_bytes() for p in _MODULES)).hexdigest()
_LIBRARIES = {name: version(name) for name in ("pypdf", "python-docx", "pydantic", "httpx")}


@dataclass(frozen=True)
class Settings:
    db: str = "var/assurance.sqlite3"
    mode: str = "local"
    provider: str = "disabled"
    provider_url: str = ""
    provider_model: str = ""
    provider_key: str = ""
    allow_external: bool = False
    provider_timeout: float = 20
    lease_seconds: float = 180
    max_attempts: int = 3
    max_bytes: int = 5_000_000

    @classmethod
    def from_env(cls):
        return cls(
            db=os.getenv("CAS_DB", cls.db),
            mode=os.getenv("CAS_MODE", "local"),
            provider=os.getenv("CAS_PROVIDER", "disabled"),
            provider_url=os.getenv("CAS_PROVIDER_URL", ""),
            provider_model=os.getenv("CAS_PROVIDER_MODEL", ""),
            provider_key=os.getenv("CAS_PROVIDER_API_KEY", ""),
            allow_external=os.getenv("CAS_ALLOW_EXTERNAL", "false").lower() == "true",
            provider_timeout=float(os.getenv("CAS_PROVIDER_TIMEOUT", "20")),
            lease_seconds=float(os.getenv("CAS_JOB_LEASE", "180")),
            max_attempts=int(os.getenv("CAS_JOB_ATTEMPTS", "3")),
        )

    def validate(self):
        if self.mode not in {"local", "production"} or self.provider not in {"disabled", "fixture", "chat"}:
            raise ValueError("Invalid mode or provider")
        if self.mode != "local" and self.provider == "fixture":
            raise ValueError("Fixture provider is limited to explicit local mode")
        if self.provider_timeout <= 0 or self.lease_seconds < 1 or self.max_attempts < 1:
            raise ValueError("Invalid timeout, lease or retry configuration")

    def evaluator(self):
        from .util import digest

        return {
            "implementation_hash": _BUILD_HASH,
            "libraries": _LIBRARIES,
            "checker": "deterministic-1",
            "extractor": "extract-1",
            "scorer": "rubric-1",
            "provider": self.provider,
            "model": self.provider_model or self.provider,
            "endpoint_hash": digest(self.provider_url),
            "prompt": "claims-1",
            "fixture": self.provider == "fixture",
        }
