import type { Metadata } from "next";
import { TelemetryClient } from "./telemetry-client";

export const metadata: Metadata = {
  title: "Salud del sistema",
  description: "Métricas operacionales de la telemetría de TrackFlow: volumen, errores, latencia y login.",
};

export default function TelemetryPage() {
  return <TelemetryClient />;
}
