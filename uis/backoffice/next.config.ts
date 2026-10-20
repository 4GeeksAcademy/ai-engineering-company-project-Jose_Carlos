import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Direcciones de antes de unificar el backoffice (HTML estático) y el Talent Pipeline
  // (que estaba en la raíz): los enlaces y marcadores antiguos siguen funcionando.
  async redirects() {
    return [
      { source: "/index.html", destination: "/", permanent: false },
      { source: "/login.html", destination: "/login", permanent: false },
      { source: "/incidents.html", destination: "/incidents", permanent: false },
      { source: "/incident-new.html", destination: "/incidents/new", permanent: false },
      { source: "/suppliers.html", destination: "/suppliers", permanent: false },
      { source: "/inventory", destination: "/inventory/products", permanent: false },
      { source: "/records/:id", destination: "/talent/records/:id", permanent: false },
    ];
  },
};

export default nextConfig;
