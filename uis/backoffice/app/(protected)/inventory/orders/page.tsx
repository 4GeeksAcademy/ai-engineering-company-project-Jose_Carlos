import type { Metadata } from "next";
import { OrdersClient } from "./orders-client";

export const metadata: Metadata = {
  title: { absolute: "Movimientos de stock | Inventario TrackFlow" },
  description: "Historial de solo lectura de entradas y salidas de stock.",
};

export default function OrdersPage() {
  return <OrdersClient />;
}
