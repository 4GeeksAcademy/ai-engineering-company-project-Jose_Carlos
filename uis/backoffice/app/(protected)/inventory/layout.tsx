"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Subnavegación común de las cuatro pantallas de inventario.
const SECTIONS = [
  { href: "/inventory/products", label: "Stock por SKU" },
  { href: "/inventory/orders/inbound", label: "Recepción de mercancía" },
  { href: "/inventory/orders/outbound", label: "Salida de stock" },
  { href: "/inventory/orders", label: "Movimientos de stock" },
];

export default function InventoryLayout({ children }: LayoutProps<"/inventory">) {
  const pathname = usePathname();
  return (
    <>
      <div className="border-b border-cyan-100 bg-cyan-50/60">
        <nav aria-label="Inventario" className="mx-auto flex max-w-6xl flex-wrap gap-1 px-4 py-2 text-sm font-semibold md:px-6">
          {SECTIONS.map((section) => {
            const active = pathname === section.href;
            return (
              <Link
                key={section.href}
                href={section.href}
                aria-current={active ? "page" : undefined}
                className={
                  active
                    ? "rounded-lg bg-cyan-700 px-3 py-2 text-white"
                    : "rounded-lg px-3 py-2 text-slate-700 transition hover:bg-cyan-100 hover:text-cyan-900"
                }
              >
                {section.label}
              </Link>
            );
          })}
        </nav>
      </div>
      {children}
    </>
  );
}
