"""Local Otto agent adapter package scaffold."""
from .gateway import (
    OPERATIONS,
    AttemptCapturePort,
    AttemptEnvelope,
    InMemoryAttemptCapture,
    OttoGateway,
    Responsibility,
    error,
)

__all__ = [
    "OPERATIONS",
    "AttemptCapturePort",
    "AttemptEnvelope",
    "InMemoryAttemptCapture",
    "OttoGateway",
    "Responsibility",
    "error",
]
