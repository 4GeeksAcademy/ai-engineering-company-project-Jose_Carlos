from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SupplierStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"

class country(str, Enum):
    USA = "USA"
    SPAIN = "SPAIN"

class currency(str, Enum):
    USD = "USD"
    EUR = "EUR"

class Supplier(BaseModel):
    name : str
    country: country
    currency: currency
    supplier_status: SupplierStatus