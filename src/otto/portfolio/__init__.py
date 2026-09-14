"""Manager-led pending-project operations over canonical Herzchen work.

The portfolio package is deliberately a boundary.  It does not persist work,
create a second event engine, or start a host session.  A caller supplies the
accepted Herzchen work-operation port and receives its durable references and
receipts unchanged.
"""

from .intake import (
    ADMISSION_CHOICES,
    EDITABLE_FIELDS,
    PortfolioError,
    OttoPortfolio,
    HerzchenWorkOperations,
    unavailable_operations,
)
from .herzchen_binding import HerzchenBindingConfig, StoreWorkOperations

__all__ = [
    "ADMISSION_CHOICES",
    "EDITABLE_FIELDS",
    "HerzchenWorkOperations",
    "HerzchenBindingConfig",
    "OttoPortfolio",
    "PortfolioError",
    "unavailable_operations",
    "StoreWorkOperations",
]
