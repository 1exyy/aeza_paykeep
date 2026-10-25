from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Attachment(Base):
    """Receipt file or link attached to one period (DOMAIN §10).

    Files live in ATTACHMENTS_DIR under a random UUID name; the original name is kept for download.
    """

    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint("kind IN ('file', 'link')", name="kind"),
        CheckConstraint(
            "(kind = 'file' AND storage_name IS NOT NULL AND url IS NULL)"
            " OR (kind = 'link' AND url IS NOT NULL AND storage_name IS NULL)",
            name="kind_fields",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurrence_id: Mapped[int] = mapped_column(
        ForeignKey("payment_occurrences.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_name: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by_login: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
