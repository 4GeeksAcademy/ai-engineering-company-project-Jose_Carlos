import type { Metadata } from "next";
import { ProductsClient } from "./products-client";

export const metadata: Metadata = {
  title: { absolute: "Stock por SKU | Inventario TrackFlow" },
  description: "Stock de cada SKU por almacén, con indicador de stock bajo.",
};

export default function ProductsPage() {
  return <ProductsClient />;
}
