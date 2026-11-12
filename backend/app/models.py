from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class OperationType(str, enum.Enum):
    RECEIPT = "receipt"
    TRANSFER_SHIP = "transfer_ship"
    TRANSFER_RECEIVE = "transfer_receive"
    FBS_RESERVE = "fbs_reserve"
    FBS_CANCEL = "fbs_cancel"
    FBS_SHIP = "fbs_ship"
    FBO_SHIP = "fbo_ship"
    FBO_RECEIVE = "fbo_receive"
    WAREHOUSE_SOFT_DELETE = "warehouse_soft_delete"


class ShipmentStatus(str, enum.Enum):
    IN_TRANSIT = "in_transit"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class FbsStatus(str, enum.Enum):
    RESERVED = "reserved"
    SHIPPED = "shipped"
    CANCELLED = "cancelled"


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    stocks: Mapped[list[StockBalance]] = relationship(back_populates="warehouse")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    stocks: Mapped[list[StockBalance]] = relationship(back_populates="product")


class StockBalance(Base):
    __tablename__ = "stock_balances"
    __table_args__ = (UniqueConstraint("warehouse_id", "product_id", name="uq_stock_wh_product"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    on_hand: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_fbs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    warehouse: Mapped[Warehouse] = relationship(back_populates="stocks")
    product: Mapped[Product] = relationship(back_populates="stocks")

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved_fbs


class Operation(Base):
    """Журнал только на добавление: подтверждённые операции, влияющие на остатки."""

    __tablename__ = "operations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    type: Mapped[OperationType] = mapped_column(
        Enum(OperationType, name="operation_type", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    from_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    to_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    product: Mapped[Product | None] = relationship()
    from_warehouse: Mapped[Warehouse | None] = relationship(foreign_keys=[from_warehouse_id])
    to_warehouse: Mapped[Warehouse | None] = relationship(foreign_keys=[to_warehouse_id])


class TransferShipment(Base):
    __tablename__ = "transfer_shipments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    from_warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    to_warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ShipmentStatus] = mapped_column(
        Enum(
            ShipmentStatus,
            name="transfer_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=ShipmentStatus.IN_TRANSIT,
        nullable=False,
    )
    ship_operation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operations.id"), nullable=True)
    receive_operation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operations.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product: Mapped[Product] = relationship()
    from_warehouse: Mapped[Warehouse] = relationship(foreign_keys=[from_warehouse_id])
    to_warehouse: Mapped[Warehouse] = relationship(foreign_keys=[to_warehouse_id])


class FboShipment(Base):
    __tablename__ = "fbo_shipments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    from_warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ShipmentStatus] = mapped_column(
        Enum(
            ShipmentStatus,
            name="fbo_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=ShipmentStatus.IN_TRANSIT,
        nullable=False,
    )
    ship_operation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operations.id"), nullable=True)
    receive_operation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operations.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product: Mapped[Product] = relationship()
    from_warehouse: Mapped[Warehouse] = relationship()


class FbsOrder(Base):
    __tablename__ = "fbs_orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[FbsStatus] = mapped_column(
        Enum(
            FbsStatus,
            name="fbs_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=FbsStatus.RESERVED,
        nullable=False,
    )
    reserve_operation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operations.id"), nullable=True)
    ship_operation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operations.id"), nullable=True)
    cancel_operation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operations.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    product: Mapped[Product] = relationship()
    warehouse: Mapped[Warehouse] = relationship()
