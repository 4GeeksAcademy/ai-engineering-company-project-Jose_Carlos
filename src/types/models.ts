export interface Envio {
    idEnvio:string,
    idPedido:string,
    idTransportista:string,
    pais:('US' | 'ES'),
    estado :('pendiente' | 'en_transito' | 'entregado' | 'incidencia')
    pesoKg:number,
    costeEnvio:number,
    fechaSalida:Date,
    fechaLlegada:Date
}
export interface Producto {
    idProducto:string,
    idEmpresa:string,
    descripcion:string,
    fechaEntrada: Date
}
export interface Transportista {
    idTransportista: string,
    nombre:string,
    pais:('US' | 'ES')
    tasaEntregaATiempo: number,
    costePorKg: number,
    incideciasRegistradas: string
}
export interface Devolución {
    idDevolucion:string,
    idPedido:string,
    motivo:string,
    estado: ('pendiente' | 'aprobada' | 'rechazada'),
    fechaSolicitud:Date,
    pais:('US' | 'ES')
}