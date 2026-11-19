import type { Metadata } from "next";
import { ReportingClient } from "./reporting-client";

export const metadata: Metadata = {
  title: "Reporte semanal de desempeño",
  description: "Volumen de entrada, throughput de salida, quiebres de stock y tasa de discrepancia por almacén y cliente.",
};

export default function ReportingPage() {
  return <ReportingClient />;
}
