import type { Metadata } from "next";
import { Suspense } from "react";
import { InboundClient } from "./inbound-client";

export const metadata: Metadata = {
  title: { absolute: "Recepción de mercancía | Inventario TrackFlow" },
  description: "Registro de entradas de stock recibidas de las marcas cliente.",
};

// InboundClient lee ?sku_id= (useSearchParams): necesita un límite de Suspense.
export default function InboundPage() {
  return (
    <Suspense>
      <InboundClient />
    </Suspense>
  );
}
