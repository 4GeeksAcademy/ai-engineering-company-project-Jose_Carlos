import { AuthGuard } from "../ui/auth-guard";

// Todas las vistas dentro de (protected) requieren sesión: listado, detalle y cuenta.
export default function ProtectedLayout({ children }: LayoutProps<"/">) {
  return <AuthGuard>{children}</AuthGuard>;
}
