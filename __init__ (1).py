"""Registry of the available knowledge bases."""

from . import car, computer, network

ALL_KBS = {m.KB.key: m.KB for m in (car, computer, network)}
