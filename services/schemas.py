"""Schemas Pydantic de request y response del inventario (/inventory).

Son el contrato de la API y van separados de los modelos ORM (services/models.py):
- Los de request no tienen `id`, `created_at`, `user_uuid` ni stock: los pone el servidor.
  Rechazan cualquier campo extra, así que enviar `current_stock` es un error, no se ignora.
- Los de response añaden lo calculado: `current_stock` y `stock_by_warehouse` del SKU.

Stock que devuelve la API (CONTEXT-9, regla 6: el stock es por SKU y por almacén):
- `current_stock`: stock del SKU en SU almacén (`warehouse`). Nunca la suma de los dos.
- `stock_by_warehouse`: desglose por almacén, por si el SKU tiene movimientos en el otro.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, computed_field, model_validator


Category = Literal["fashion", "electronics", "cosmetics"]
Warehouse = Literal["LA", "ZGZ"]
ExitType = Literal["dispatch", "loss"]

# Una cantidad cabe siempre en la columna INTEGER de PostgreSQL.
MAX_QUANTITY = 2_147_483_647

Quantity = Annotated[StrictInt, Field(gt=0, le=MAX_QUANTITY)]
SKUId = Annotated[StrictInt, Field(gt=0)]


class _Request(BaseModel):
    # Los textos llegan sin espacios alrededor; un texto solo de espacios queda vacío y no pasa min_length.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# =========================================================
# SKU
# =========================================================


class SKUCreate(_Request):
    name: str = Field(min_length=1, max_length=200)
    sku: str = Field(min_length=1, max_length=64)
    client_name: str = Field(min_length=1, max_length=120)
    category: Category
    warehouse: Warehouse


class SKUSummary(BaseModel):
    """Datos del SKU que acompañan a cada movimiento en GET /inventory/orders."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sku: str
    client_name: str
    category: Category
    warehouse: Warehouse


class SKURead(SKUSummary):
    current_stock: int = Field(description="Stock del SKU en su almacén (`warehouse`). Calculado, no almacenado.")
    stock_by_warehouse: dict[Warehouse, int] = Field(
        description="Stock por almacén: entradas menos salidas de cada uno. Nunca se suman."
    )


# =========================================================
# MOVIMIENTOS: entradas y salidas de stock
# =========================================================


class StockEntryCreate(_Request):
    sku_id: SKUId
    quantity: Quantity
    reference: str = Field(min_length=1, max_length=64, description="Referencia de despacho del cliente, p. ej. PO-2024-0098.")
    warehouse: Warehouse


class StockExitCreate(_Request):
    sku_id: SKUId
    quantity: Quantity
    exit_type: ExitType
    tracking_number: str | None = Field(default=None, min_length=1, max_length=64)
    warehouse: Warehouse

    @model_validator(mode="after")
    def check_tracking_number(self):
        # CONTEXT-9, regla 3.
        if self.exit_type == "dispatch" and self.tracking_number is None:
            raise ValueError("tracking_number is required when exit_type is 'dispatch'")
        if self.exit_type == "loss" and self.tracking_number is not None:
            raise ValueError("tracking_number must be null when exit_type is 'loss'")
        return self


class _OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku_id: int
    quantity: int
    warehouse: Warehouse
    created_at: datetime
    user_uuid: str
    sku: SKUSummary


class StockEntryRead(_OrderRead):
    order_type: Literal["inbound"] = "inbound"
    reference: str


class StockExitRead(_OrderRead):
    order_type: Literal["outbound"] = "outbound"
    exit_type: ExitType
    tracking_number: str | None


# Respuesta de un alta (POST /inventory/orders/*): el movimiento más el stock que deja en su
# almacén. El backoffice lo necesita para el evento de telemetría (`stock_after`) sin otra
# consulta. El listado (GET /inventory/orders) no lo lleva: sería un cálculo por fila.
_STOCK_AFTER = Field(ge=0, description="Stock del SKU en el almacén del movimiento justo después de registrarlo.")


class StockEntryCreated(StockEntryRead):
    stock_after: int = _STOCK_AFTER


class StockExitCreated(StockExitRead):
    stock_after: int = _STOCK_AFTER


# =========================================================
# UMBRALES Y CONTEOS (telemetría, TELEMETRY_PLAN.md PR-1 y PR-2)
# =========================================================

CountType = Literal["cycle_count", "full_audit"]
MinStock = Annotated[StrictInt, Field(gt=0, le=MAX_QUANTITY)]
CountedQuantity = Annotated[StrictInt, Field(ge=0, le=MAX_QUANTITY)]


class StockThresholdSet(_Request):
    """Fija (o sustituye) el stock mínimo de un SKU en un almacén. Es configuración, no stock."""

    sku_id: SKUId
    warehouse: Warehouse
    min_stock: MinStock


class StockThresholdRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku_id: int
    warehouse: Warehouse
    min_stock: int
    updated_at: datetime
    user_uuid: str


class StockCountCreate(_Request):
    """Conteo físico. El stock del sistema lo calcula la API: el cliente solo envía lo contado."""

    sku_id: SKUId
    warehouse: Warehouse
    counted_quantity: CountedQuantity
    count_type: CountType = "cycle_count"


class StockCountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku_id: int
    warehouse: Warehouse
    counted_quantity: int
    system_quantity: int
    count_type: CountType
    created_at: datetime
    user_uuid: str
    sku: SKUSummary

    @computed_field(description="counted_quantity − system_quantity: negativo = faltan unidades.")
    @property
    def difference(self) -> int:
        return self.counted_quantity - self.system_quantity


# =========================================================
# LISTADO DE MOVIMIENTOS (GET /inventory/orders)
# =========================================================
# Más ligero que la respuesta de un alta: sin `sku_id` (el objeto `sku` ya identifica el SKU)
# y con el SKU reducido a lo que muestra la tabla. `sku` sigue anidado porque el backoffice
# lo lee como `order.sku.sku`.


class SKURef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku: str
    name: str
    client_name: str


class _OrderListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    quantity: int
    warehouse: Warehouse
    created_at: datetime
    user_uuid: str = Field(description="Id del usuario que registró el movimiento.")
    sku: SKURef


class StockEntryListItem(_OrderListItem):
    order_type: Literal["inbound"] = "inbound"
    reference: str


class StockExitListItem(_OrderListItem):
    order_type: Literal["outbound"] = "outbound"
    exit_type: ExitType
    tracking_number: str | None


# Un elemento de GET /inventory/orders: `order_type` dice si es una entrada o una salida.
StockOrderListItem = Annotated[StockEntryListItem | StockExitListItem, Field(discriminator="order_type")]
