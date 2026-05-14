"""SQLAlchemy schema foundation for pi-memory."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for pi-memory ORM models."""
