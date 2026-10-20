import type { Metadata } from "next";
import { Suspense } from "react";
import { OutboundClient } from "./outbound-client";

export const metadata: Metadata = {
  title: { absolute: "Salida de stock | Inventario TrackFlow" },
  description: "Registro de despachos y pérdidas, con el stock disponible antes de enviar.",
};

// OutboundClient lee ?sku_id= (useSearchParams): necesita un límite de Suspense.
export default function OutboundPage() {
  return (
    <Suspense>
      <OutboundClient />
    </Suspense>
  );
}
