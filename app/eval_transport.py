"""Evaluation-only network limits; these do not change models or scoring inputs."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelTransport:
    timeout: float = 20.0
    max_retries: int = 2
    structured_attempts: int = 2


_policy = ContextVar('model_transport', default=ModelTransport())


def model_transport():
    return _policy.get()


@contextmanager
def evaluation_transport():
    # The evaluator owns retries. Avoid SDK × parser × evaluator retry multiplication.
    token = _policy.set(ModelTransport(timeout=90.0, max_retries=0, structured_attempts=1))
    try:
        yield
    finally:
        _policy.reset(token)
