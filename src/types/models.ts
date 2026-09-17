export interface Envio {
    idEnvio: string,
    idProducto: string,
    idTransportista: string,
    pais: 'US' | 'ES',
    estado: 'pendiente' | 'en_transito' | 'entregado' | 'incidencia',
    costeEnvio: number,
    pesoTotal: number,
    fechaSalida: Date,
    fechaLlegada:Date
}

export interface Producto {
    idProducto: string,
    idEmpresa: string,
    pesoKg: number,
    descripcion: string,
    precio: number,
    cantidad: number
}

export interface Transportista {
    idTransportista: string,
    nombreEmpresa: string,
    pais: 'US' | 'ES',
    tasaEntregaATiempo: number,
    costePorKg: number,
    incidenciasRegistradas: string[]
}

export interface Devolucion {
    idDevolucion: string,
    idEnvio: string,
    idProducto: string,
    motivo: string,
    estado: 'pendiente' | 'aprobada' | 'rechazada',
    fechaSolicitud: Date
}

export type Devolución = Devolucion

export const envioEjemplo: Envio = {
    idEnvio: 'ENV-001',
    idProducto: 'PROD-001',
    idTransportista: 'TRANS-UPS',
    pais: 'US',
    estado: 'entregado',
    costeEnvio: 12.5,
    pesoTotal: 2.4,
    fechaSalida: new Date('2026-09-15T09:00:00Z'),
    fechaLlegada: new Date('2026-09-16T16:30:00Z'),
}

export const productoEjemplo: Producto = {
    idProducto: 'PROD-001',
    idEmpresa: 'CLIENTE-001',
    pesoKg: 2.4,
    descripcion: 'Pedido de comercio electrónico',
    precio: 49.99,
    cantidad: 1,
}

export const transportistaEjemplo: Transportista = {
    idTransportista: 'TRANS-UPS',
    nombreEmpresa: 'UPS',
    pais: 'US',
    tasaEntregaATiempo: 96,
    costePorKg: 5.2,
    incidenciasRegistradas: [],
}

export const devolucionEjemplo: Devolucion = {
    idDevolucion: 'DEV-001',
    idEnvio: 'ENV-001',
    idProducto: 'PROD-001',
    motivo: 'Producto dañado',
    estado: 'aprobada',
    fechaSolicitud: new Date('2026-09-17T10:00:00Z'),
}