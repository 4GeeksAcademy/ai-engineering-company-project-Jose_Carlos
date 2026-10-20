import type { Metadata } from "next";
import { Geist } from "next/font/google";
import "./globals.css";

// Solo Geist Sans: la variable de Geist Mono no la usaba ningún estilo (`font-mono` es la pila
// monoespaciada del sistema), pero su fichero se precargaba en todas las páginas.
const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    template: "%s | TrackFlow",
    default: "TrackFlow Backoffice",
  },
  description: "Backoffice de TrackFlow: incidencias, proveedores, inventario y Talent Pipeline.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="es"
      className={`${geistSans.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
