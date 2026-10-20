import type { Metadata } from "next";
import { Suspense } from "react";
import { HomeClient } from "../../ui/home-client";

export const metadata: Metadata = {
  title: "Talent Pipeline",
  description: "Gestor de candidaturas con filtros, detalle y notas internas.",
};

export default function TalentHome() {
  return (
    <Suspense fallback={<div className="p-6">Cargando...</div>}>
      <HomeClient />
    </Suspense>
  );
}
