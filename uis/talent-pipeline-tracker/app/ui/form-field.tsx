import { InputHTMLAttributes } from "react";

type FormFieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  name: string;
  error?: string;
};

/** Input con etiqueta y mensaje de error de campo (usado por login, registro y perfil). */
export function FormField({ label, name, error, className, ...props }: FormFieldProps) {
  const errorId = `${name}-error`;
  return (
    <div>
      <label htmlFor={name} className="mb-1 block text-sm font-semibold text-slate-700">
        {label}
      </label>
      <input
        id={name}
        name={name}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? errorId : undefined}
        className={`w-full rounded-lg border bg-white px-3 py-2 text-sm outline-none focus:ring ${
          error ? "border-red-400 ring-red-200" : "border-cyan-200 ring-cyan-200"
        } ${className ?? ""}`}
        {...props}
      />
      {error && (
        <p id={errorId} className="mt-1 text-xs text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}
