import { AuthGuard } from "../ui/auth-guard";
import { BackofficeHeader } from "../ui/backoffice-header";

// Todas las vistas dentro de (protected) requieren sesión: backoffice (incidencias, proveedores,
// inventario), Talent Pipeline y cuenta. Comparten la cabecera con las secciones del backoffice.
export default function ProtectedLayout({ children }: LayoutProps<"/">) {
  return (
    <AuthGuard>
      <div className="min-h-screen bg-cyan-50 text-slate-800">
        <BackofficeHeader />
        {children}
      </div>
    </AuthGuard>
  );
}
