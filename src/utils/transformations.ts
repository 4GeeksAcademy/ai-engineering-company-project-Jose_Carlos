/* Funciones de cálculo */

export function calcTotal(arr: readonly number[]): number {
    return arr.reduce((total, valor) => total + valor, 0)
}

export function calcMedia(arr: readonly number[]): number | undefined {
    return arr.length === 0 ? undefined : calcTotal(arr) / arr.length
}

export function calcMax(arr: readonly number[]): number | undefined {
    return arr.length === 0
        ? undefined
        : arr.reduce((maximo, valor) => Math.max(maximo, valor))
}

export function calcMin(arr: readonly number[]): number | undefined {
    return arr.length === 0
        ? undefined
        : arr.reduce((minimo, valor) => Math.min(minimo, valor))
}

export function contarPorCategoria<T extends string | number>(
    arr: readonly T[],
): Record<string, number> {
    return arr.reduce<Record<string, number>>((conteo, categoria) => {
        const clave = String(categoria)

        return {
            ...conteo,
            [clave]: (conteo[clave] ?? 0) + 1,
        }
    }, {})
}