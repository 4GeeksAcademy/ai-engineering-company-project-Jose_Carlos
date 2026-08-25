import Link from "next/link";

export function TrackflowHeader() {
  return (
    <header className="fixed top-0 z-50 w-full border-b border-cyan-100 bg-white/95 backdrop-blur">
      <nav
        className="relative mx-auto flex max-w-7xl items-center justify-center gap-2 px-4 py-3 md:px-6"
        aria-label="Navegacion principal"
      >
        <Link
          href="/"
          className="text-2xl font-extrabold tracking-tight text-cyan-700"
        >
          TrackFlow
        </Link>
      </nav>
    </header>
  );
}
