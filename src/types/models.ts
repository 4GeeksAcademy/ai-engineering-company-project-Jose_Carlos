interface Envio {
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
interface Producto {
    idProducto:string,
    idEmpresa:string,
    descripcion:string,
    fechaEntrada: Date
}
interface Transportista {
    idTransportista: string,
    nombre:string,
    pais:('US' | 'ES')
    tasaEntregaATiempo: number,
    costePorKg: number,
    incideciasRegistradas: string
}
interface Devolución {
    idDevolucion:string,
    idPedido:string,
    motivo:string,
    estado: ('pendiente' | 'aprobada' | 'rechazada'),
    fechaSolicitud:Date,
    pais:('US' | 'ES')
}