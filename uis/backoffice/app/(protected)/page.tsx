import type { Metadata } from "next";
import { AnalyzerClient } from "./analyzer-client";

export const metadata: Metadata = {
  title: "Analizador de incidentes",
  description: "Analiza archivos CSV de incidentes y consulta sus resultados.",
};

export default function AnalyzerPage() {
  return <AnalyzerClient />;
}
