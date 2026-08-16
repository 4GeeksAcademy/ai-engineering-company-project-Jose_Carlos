export interface Envio {
    idEnvio:string,
    idProducto:string,
    idTransportista:string,
    pais:('US' | 'ES'),
    estado :('pendiente' | 'en_transito' | 'entregado' | 'incidencia'),
    costeEnvio:number,
    pesoTotal:number,
    fechaSalida:Date,
    fechaLlegada:Date
}
export interface Producto {
    idProducto:string,
    idEmpresa:string,
    pesoKg:number,
    descripcion:string,
    precio:number,
    cantidad:number
}
export interface Transportista {
    idTransportista: string,
    nombreEmpresa:string,
    pais:('US' | 'ES'),
    tasaEntregaATiempo: number,
    costePorKg: number,
    incideciasRegistradas: string[]
}
export interface Devolución {
    idDevolucion:string,
    idEnvio:string,
    idProducto:string,
    motivo:string,
    estado: ('pendiente' | 'aprobada' | 'rechazada'),
    fechaSolicitud:Date
}