from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SystemState(Base):
    """Single-row table with process-independent state (dev clock offset)."""

    __tablename__ = "system_state"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    clock_offset_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
