import type { Metadata } from "next";
import { IncidentFormClient } from "./incident-form-client";

export const metadata: Metadata = {
  title: "Registrar incidencia",
  description: "Registro de incidencias operativas y de clientes de TrackFlow.",
};

export default function NewIncidentPage() {
  return <IncidentFormClient />;
}
