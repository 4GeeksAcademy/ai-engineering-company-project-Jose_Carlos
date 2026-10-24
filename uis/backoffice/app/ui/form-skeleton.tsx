// Hueco que ocupa un formulario cargado con next/dynamic mientras llega su código:
// mismos bordes, alturas y separación que los campos reales, para que al aparecer el
// formulario la página no salte.
export function FormSkeleton({ fields, className }: { fields: number; className: string }) {
  return (
    <div role="status" aria-label="Cargando formulario" className={className}>
      {Array.from({ length: fields }, (_, index) => (
        <div key={index} className="h-[38px] animate-pulse rounded-lg border border-cyan-100 bg-cyan-50" />
      ))}
      <div className="h-9 w-40 animate-pulse rounded-lg bg-cyan-100" />
    </div>
  );
}
