import { Suspense } from "react";
import { HomeClient } from "./ui/home-client";

export default function Home() {
  return (
    <Suspense fallback={<div className="p-6">Cargando...</div>}>
      <HomeClient />
    </Suspense>
  );
}
