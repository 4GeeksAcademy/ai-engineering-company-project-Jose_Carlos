from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# --------------------------------------------------
# ENUMS
# --------------------------------------------------

class SupplierStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class SupplierCategory(str, Enum):
    CARRIER_LAST_MILE = "carrier_last_mile"
    CARRIER_INTERNATIONAL = "carrier_international"
    WAREHOUSE_SUPPLIES = "warehouse_supplies"
    PACKAGING_MATERIALS = "packaging_materials"
    REVERSE_LOGISTICS = "reverse_logistics"
    FLEET_MAINTENANCE = "fleet_maintenance"
    IT_AND_WMS_SOFTWARE = "it_and_wms_software"
    CLEANING_AND_FACILITIES = "cleaning_and_facilities"


# --------------------------------------------------
# MODELO BASE
# --------------------------------------------------

class SupplierBase(BaseModel):
    name: str = Field(..., min_length=1)
    country: Literal["USA", "Spain"]
    categories: list[SupplierCategory] = Field(..., min_length=1)

    rate_per_shipment: float = Field(..., gt=0)

    currency: Literal["USD", "EUR"]
    status: SupplierStatus

    service_zone: str | None = None
    contact_email: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_country_currency(self):
        if self.country == "USA" and self.currency != "USD":
            raise ValueError("USA suppliers must use USD")

        if self.country == "Spain" and self.currency != "EUR":
            raise ValueError("Spain suppliers must use EUR")

        return self


# --------------------------------------------------
# CREAR PROVEEDOR
# --------------------------------------------------

# No declara id ni updated_at: si el cliente los envía, Pydantic los ignora
# (extra="ignore" por defecto) y el servidor genera ambos.
class SupplierCreate(SupplierBase):
    # Un JSON con `1e999` llega como infinito: se rechaza aquí, en la entrada, porque
    # guardado no se puede devolver como número.
    rate_per_shipment: float = Field(..., gt=0, allow_inf_nan=False)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name must not be blank")
        return value


# --------------------------------------------------
# RESPUESTA DE LA API
# --------------------------------------------------

class SupplierResponse(SupplierBase):
    id: int
    updated_at: datetime


# --------------------------------------------------
# ACTUALIZAR TARIFA
# --------------------------------------------------

class SupplierRateUpdate(BaseModel):
    rate_per_shipment: float = Field(..., gt=0, allow_inf_nan=False)


# --------------------------------------------------
# CAMBIAR ESTADO
# --------------------------------------------------

class SupplierStatusUpdate(BaseModel):
    status: SupplierStatus


# Alias con los nombres cortos usados en la especificación del milestone.
RateUpdate = SupplierRateUpdate
StatusUpdate = SupplierStatusUpdate
