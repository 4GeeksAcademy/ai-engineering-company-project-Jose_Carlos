import type {
    Devolucion,
    Envio,
    Producto,
    Transportista,
} from '../types/models'

export type EntidadTrackFlow = Envio | Producto | Transportista | Devolucion

function esTextoObligatorio(valor: string): boolean {
    return valor.trim().length > 0
}

function esNumeroFinitoNoNegativo(valor: number): boolean {
    return Number.isFinite(valor) && valor >= 0
}

function esFechaValida(fecha: Date): boolean {
    return fecha instanceof Date && !Number.isNaN(fecha.getTime())
}

export function validarEnvio(envio: Envio): boolean {
    return (
        esTextoObligatorio(envio.idEnvio) &&
        esTextoObligatorio(envio.idProducto) &&
        esTextoObligatorio(envio.idTransportista) &&
        (envio.pais === 'US' || envio.pais === 'ES') &&
        ['pendiente', 'en_transito', 'entregado', 'incidencia'].includes(envio.estado) &&
        esNumeroFinitoNoNegativo(envio.costeEnvio) &&
        esNumeroFinitoNoNegativo(envio.pesoTotal) &&
        esFechaValida(envio.fechaSalida) &&
        esFechaValida(envio.fechaLlegada) &&
        envio.fechaLlegada.getTime() >= envio.fechaSalida.getTime()
    )
}

export function validarProducto(producto: Producto): boolean {
    return (
        esTextoObligatorio(producto.idProducto) &&
        esTextoObligatorio(producto.idEmpresa) &&
        esTextoObligatorio(producto.descripcion) &&
        esNumeroFinitoNoNegativo(producto.pesoKg) &&
        esNumeroFinitoNoNegativo(producto.precio) &&
        Number.isInteger(producto.cantidad) &&
        producto.cantidad >= 0
    )
}

export function validarTransportista(transportista: Transportista): boolean {
    return (
        esTextoObligatorio(transportista.idTransportista) &&
        esTextoObligatorio(transportista.nombreEmpresa) &&
        (transportista.pais === 'US' || transportista.pais === 'ES') &&
        Number.isFinite(transportista.tasaEntregaATiempo) &&
        transportista.tasaEntregaATiempo >= 0 &&
        transportista.tasaEntregaATiempo <= 100 &&
        esNumeroFinitoNoNegativo(transportista.costePorKg) &&
        transportista.incidenciasRegistradas.every(esTextoObligatorio)
    )
}

export function validarDevolucion(devolucion: Devolucion): boolean {
    return (
        esTextoObligatorio(devolucion.idDevolucion) &&
        esTextoObligatorio(devolucion.idEnvio) &&
        esTextoObligatorio(devolucion.idProducto) &&
        esTextoObligatorio(devolucion.motivo) &&
        ['pendiente', 'aprobada', 'rechazada'].includes(devolucion.estado) &&
        esFechaValida(devolucion.fechaSolicitud)
    )
}

function validarEntidad(entidad: EntidadTrackFlow): boolean {
    if ('idDevolucion' in entidad) {
        return validarDevolucion(entidad)
    }

    if ('idTransportista' in entidad && 'nombreEmpresa' in entidad) {
        return validarTransportista(entidad)
    }

    if ('idEnvio' in entidad) {
        return validarEnvio(entidad)
    }

    return validarProducto(entidad)
}

export function validacion(arr: readonly EntidadTrackFlow[]): boolean {
    return arr.every(validarEntidad)
}