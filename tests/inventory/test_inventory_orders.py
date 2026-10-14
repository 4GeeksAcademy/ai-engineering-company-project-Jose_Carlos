"""GET /inventory/orders — todos los movimientos de stock con los datos del SKU."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import TypeAdapter

from services import inventory_service
from services.routers.inventory import list_orders
from services.schemas import StockEntryRead, StockExitRead, StockOrderRead


def test_orders_list_entries_and_exits_with_their_sku(db, make_sku, receive, dispatch, operator):
    sneaker = make_sku()
    serum = make_sku(sku="CSM-SRM-030", name="Sérum facial hidratante 30ml", category="cosmetics", warehouse="ZGZ")
    receive(sneaker, 120)
    receive(serum, 200)
    dispatch(sneaker, 30)

    orders = list_orders(db=db)

    assert [type(order) for order in orders].count(StockEntryRead) == 2
    assert [type(order) for order in orders].count(StockExitRead) == 1
    assert {order.sku.sku for order in orders} == {"CLT-SNK-W-42", "CSM-SRM-030"}
    assert {order.user_uuid for order in orders} == {operator["id"]}
    [stock_exit] = [order for order in orders if order.order_type == "outbound"]
    assert (stock_exit.quantity, stock_exit.tracking_number, stock_exit.sku.client_name) == (
        30, "1Z999AA10123456784", "PureStep Footwear",
    )


def test_orders_are_listed_newest_first(db, sneaker, receive, dispatch):
    start = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
    movements = [receive(sneaker, 10, reference="PO-1"), dispatch(sneaker, 3), receive(sneaker, 5, reference="PO-2")]
    for minute, movement in enumerate(movements):
        movement.created_at = start + timedelta(minutes=minute)
        db.add(movement)
    db.commit()

    orders = list_orders(db=db)

    assert [(order.order_type, order.quantity) for order in orders] == [
        ("inbound", 5), ("outbound", 3), ("inbound", 10),
    ]


def test_orders_on_empty_inventory_is_empty(db, sneaker):
    assert list_orders(db=db) == []


def test_rejected_exit_does_not_appear_in_the_orders(db, sneaker, receive, dispatch):
    receive(sneaker, 5)
    with pytest.raises(inventory_service.InsufficientStock):
        dispatch(sneaker, 6)

    assert [order.order_type for order in list_orders(db=db)] == ["inbound"]


def test_each_order_type_validates_against_the_union_schema(db, sneaker, receive, dispatch):
    receive(sneaker, 10)
    dispatch(sneaker, 1, exit_type="loss")

    dumped = [order.model_dump() for order in list_orders(db=db)]
    parsed = TypeAdapter(list[StockOrderRead]).validate_python(dumped)

    assert {type(order) for order in parsed} == {StockEntryRead, StockExitRead}
