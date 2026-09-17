/* Funciones para manejar Arrays */

/* Funciones de añadir (Para String y Number) */
export function añadirString(arr: readonly string[], elemento: string): string[] {
    return [...arr, elemento]
}

export function añadirNumber(arr: readonly number[], elemento: number): number[] {
    return [...arr, elemento]
}

/* Funciones de filtrar (Para String y Number) */
export function filtrarEnvios(arr: readonly number[], criterio: number): number[] {
    return arr.filter((envio) => envio === criterio)
}

export function filtrarPorString(arr: readonly string[], criterio: string): string[] {
    return arr.filter((elemento) => elemento === criterio)
}

export const filtarEnvios = filtrarEnvios
export const filtarPorString = filtrarPorString

export function ordenarNumeros(
    arr: readonly number[],
    orden: 'ascendente' | 'descendente' = 'ascendente',
): number[] {
    const factor = orden === 'ascendente' ? 1 : -1
    return [...arr].sort((a, b) => (a - b) * factor)
}

export function ordenarStrings(
    arr: readonly string[],
    orden: 'ascendente' | 'descendente' = 'ascendente',
): string[] {
    const factor = orden === 'ascendente' ? 1 : -1
    return [...arr].sort((a, b) => a.localeCompare(b) * factor)
}

export function agruparPor<T, K extends PropertyKey>(
    arr: readonly T[],
    obtenerCategoria: (elemento: T) => K,
): Record<K, T[]> {
    return arr.reduce<Record<K, T[]>>((grupos, elemento) => {
        const categoria = obtenerCategoria(elemento)
        const grupo = grupos[categoria] ?? []

        return {
            ...grupos,
            [categoria]: [...grupo, elemento],
        }
    }, {} as Record<K, T[]>)
}
