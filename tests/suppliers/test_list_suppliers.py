"""GET /suppliers — list_suppliers y sus filtros."""

import pytest

from services.api.models import SupplierCategory
from services.api.routes.suppliers import list_suppliers


def _names(suppliers):
    return sorted(supplier["name"] for supplier in suppliers)


@pytest.fixture
def directory(make_supplier):
    make_supplier(name="Ebro", categories=["carrier_last_mile"])
    make_supplier(name="Pirineos", categories=["packaging_materials", "carrier_last_mile"])
    make_supplier(name="LA Freight", country="USA", currency="USD", categories=["carrier_last_mile"])
    make_supplier(name="Pacific Boxes", country="USA", currency="USD", categories=["packaging_materials"])


# =========================================================
# Camino feliz
# =========================================================


def test_list_returns_every_supplier(directory):
    assert _names(list_suppliers()) == ["Ebro", "LA Freight", "Pacific Boxes", "Pirineos"]


def test_list_filters_by_country(directory):
    assert _names(list_suppliers(country="Spain")) == ["Ebro", "Pirineos"]
    assert _names(list_suppliers(country="USA")) == ["LA Freight", "Pacific Boxes"]


def test_list_filters_by_category(directory):
    found = list_suppliers(category=SupplierCategory.PACKAGING_MATERIALS)

    assert _names(found) == ["Pacific Boxes", "Pirineos"]


# =========================================================
# Casos límite
# =========================================================


def test_list_is_empty_when_there_are_no_suppliers():
    assert list_suppliers() == []
    assert list_suppliers(country="Spain", category=SupplierCategory.CARRIER_LAST_MILE) == []


def test_list_combines_country_and_category_with_and(directory):
    found = list_suppliers(country="USA", category=SupplierCategory.PACKAGING_MATERIALS)

    assert _names(found) == ["Pacific Boxes"]


def test_supplier_with_several_categories_is_listed_under_each(directory):
    last_mile = list_suppliers(category=SupplierCategory.CARRIER_LAST_MILE)
    packaging = list_suppliers(category=SupplierCategory.PACKAGING_MATERIALS)

    assert "Pirineos" in _names(last_mile)
    assert "Pirineos" in _names(packaging)


def test_list_includes_suspended_suppliers(make_supplier):
    make_supplier(name="Parado", status="suspended")

    assert [supplier["status"] for supplier in list_suppliers()] == ["suspended"]


# =========================================================
# Modos de fallo
# =========================================================


def test_filter_without_matches_returns_an_empty_list_not_an_error(directory):
    assert list_suppliers(category=SupplierCategory.FLEET_MAINTENANCE) == []


def test_filters_do_not_modify_the_stored_suppliers(directory):
    list_suppliers(country="Spain")

    assert len(list_suppliers()) == 4
