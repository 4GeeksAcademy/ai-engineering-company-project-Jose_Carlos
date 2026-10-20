import type { Metadata } from "next";
import { SuppliersClient } from "./suppliers-client";

export const metadata: Metadata = {
  title: "Directorio de proveedores",
  description: "Directorio centralizado de proveedores de TrackFlow en USA y España.",
};

export default function SuppliersPage() {
  return <SuppliersClient />;
}
