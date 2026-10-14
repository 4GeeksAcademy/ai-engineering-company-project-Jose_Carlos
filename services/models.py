"""Modelos ORM (SQLModel) del inventario en Supabase: SKU, StockEntry y StockExit.

Son las tablas, no el contrato de la API: los endpoints responden siempre con los schemas
de services/schemas.py, nunca con estos objetos.

- El SKU no tiene columna de stock. El stock se calcula siempre a partir de los movimientos
  (services/inventory_service.py), así que no hay forma de fijarlo directamente.
- StockEntry y StockExit referencian el SKU con una FK real en la base de datos.
- `user_uuid` es el id del usuario de TinyDB: texto sin FK, porque los usuarios no se
  replican en Supabase.
- Las restricciones CHECK repiten en la base de datos las reglas de los schemas, para que
  ninguna escritura (aunque no pase por la API) deje datos imposibles.
"""

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime
from sqlmodel import Field, Relationship, SQLModel


# Valores permitidos (CONTEXT-9). services/schemas.py declara los mismos como Literal.
CATEGORIES = ("fashion", "electronics", "cosmetics")
WAREHOUSES = ("LA", "ZGZ")
EXIT_TYPES = ("dispatch", "loss")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class SKU(SQLModel, table=True):
    """Un artículo de una marca cliente, registrado en un almacén."""

    __tablename__ = "sku"
    __table_args__ = (
        CheckConstraint(_one_of("category", CATEGORIES), name="ck_sku_category"),
        CheckConstraint(_one_of("warehouse", WAREHOUSES), name="ck_sku_warehouse"),
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=200)
    # Código asignado por la marca cliente: identifica el SKU, así que es único.
    sku: str = Field(max_length=64, unique=True, index=True)
    client_name: str = Field(max_length=120)
    category: str = Field(max_length=20)
    warehouse: str = Field(max_length=3)

    entries: list["StockEntry"] = Relationship(back_populates="sku")
    exits: list["StockExit"] = Relationship(back_populates="sku")


class StockEntry(SQLModel, table=True):
    """Recepción de mercancía de una marca cliente: suma stock en un almacén."""

    __tablename__ = "stock_entry"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_stock_entry_quantity"),
        CheckConstraint(_one_of("warehouse", WAREHOUSES), name="ck_stock_entry_warehouse"),
    )

    id: int | None = Field(default=None, primary_key=True)
    sku_id: int = Field(foreign_key="sku.id", ondelete="RESTRICT", index=True)
    quantity: int
    reference: str = Field(max_length=64)
    warehouse: str = Field(max_length=3)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True), nullable=False)
    user_uuid: str = Field(max_length=36, index=True)

    sku: SKU = Relationship(back_populates="entries")


class StockExit(SQLModel, table=True):
    """Despacho a un cliente final o baja por pérdida: resta stock de un almacén."""

    __tablename__ = "stock_exit"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_stock_exit_quantity"),
        CheckConstraint(_one_of("warehouse", WAREHOUSES), name="ck_stock_exit_warehouse"),
        CheckConstraint(_one_of("exit_type", EXIT_TYPES), name="ck_stock_exit_type"),
        # Un despacho lleva número de seguimiento; una pérdida, nunca.
        CheckConstraint(
            "(exit_type = 'dispatch' AND tracking_number IS NOT NULL)"
            " OR (exit_type = 'loss' AND tracking_number IS NULL)",
            name="ck_stock_exit_tracking_number",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    sku_id: int = Field(foreign_key="sku.id", ondelete="RESTRICT", index=True)
    quantity: int
    exit_type: str = Field(max_length=10)
    tracking_number: str | None = Field(default=None, max_length=64)
    warehouse: str = Field(max_length=3)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True), nullable=False)
    user_uuid: str = Field(max_length=36, index=True)

    sku: SKU = Relationship(back_populates="exits")
