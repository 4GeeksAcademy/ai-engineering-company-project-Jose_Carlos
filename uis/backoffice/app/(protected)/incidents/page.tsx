import type { Metadata } from "next";
import { IncidentsManagerClient } from "./incidents-manager-client";

export const metadata: Metadata = {
  title: "Gestor de incidencias",
  description: "Gestor centralizado de incidencias de TrackFlow: resumen, listado y cambio de estado.",
};

export default function IncidentsPage() {
  return <IncidentsManagerClient />;
}
