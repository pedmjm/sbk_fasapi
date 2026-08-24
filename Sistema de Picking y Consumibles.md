Sistema de Picking y Consumibles — Resumen de Endpoints
Tablas Nuevas
Tabla	Descripción
consumibles	Insumos y materiales consumibles del inventario
pickings	Órdenes de picking (lista de herramientas y consumibles a recoger)
picking_items	Ítems individuales dentro de un picking
picking_personal	Asignación de técnicos a un picking (M:N)
tarea_picking	Relación de un picking con una tarea (M:N)
Flujo General

CREADOR (tipo_usuario >= 1)              TÉCNICO (asignado)
─────────────────────────                ──────────────────

    Crea el picking                        
         

        referencia, motivo                   
         

        selecciona items del catálogo       
         

        asigna técnicos                      
                              2. Ve su lista de pickings
                              3. Marca items: tomado / 
                                 no_disponible / innecesario
                              4. Agrega items que faltan

    Completa o cancela el picking

text
 
  
 
 

---

## Consumibles

### `GET /consumibles` — Listar consumibles

 
 

GET /consumibles
GET /consumibles?tipo=Eléctrico
GET /consumibles?estado=Disponible
GET /consumibles?low_stock=true
GET /consumibles?search=cable
text
 
  
 
 

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `tipo` | query | Filtrar por tipo (`Eléctrico`, `Mecánico`, `Seguridad`, `Limpieza`, `Soldadura`, `Pintura`, `Tubería`, `Otro`) |
| `estado` | query | Filtrar por estado |
| `low_stock` | query bool | `true` para ver solo los que están por debajo del stock mínimo |
| `search` | query | Busca por nombre (substring) |

**Auth:** Cualquier usuario activo

---

### `GET /consumibles/stats` — Estadísticas

 
 

GET /consumibles/stats
text
 
  
 
 

Respuesta:
```json
{
  "data": {
    "total": 42,
    "low_stock": 3,
    "by_type": {
      "Eléctrico": 12,
      "Mecánico": 8
    }
  }
}
 
 

Auth: Cualquier usuario activo
GET /consumibles/{id} — Ver uno
text
 
  
 
 
GET /consumibles/550e8400-e29b-41d4-a716-446655440000
 
 

Auth: Cualquier usuario activo
POST /consumibles — Crear
text
 
  
 
 
POST /consumibles
 
 
json
 
  
 
 
{
  "nombre": "Cable AWG 12",
  "descripcion": "Cable de cobre 12AWG rojo",
  "tipo": "Eléctrico",
  "unidad_medida": "metro",
  "stock_actual": 100,
  "stock_minimo": 20,
  "estado": "Disponible"
}
 
 

Auth: Admin únicamente
PUT /consumibles/{id} — Actualizar

Cualquier campo puede omitirse (actualización parcial):
text
 
  
 
 
PUT /consumibles/550e8400-e29b-41d4-a716-446655440000
 
 
json
 
  
 
 
{
  "stock_actual": 85,
  "estado": "Disponible"
}
 
 

Auth: Admin únicamente
PATCH /consumibles/{id}/stock — Ajustar stock

Suma o resta cantidad al stock actual:
text
 
  
 
 
PATCH /consumibles/550e8400-e29b-41d4-a716-446655440000?cantidad=-15
 
 
Parámetro
	
Tipo
	
Descripción
cantidad	query int (requerido)	Positivo para sumar, negativo para restar
 
 

Si el resultado queda <= stock_minimo, la respuesta incluye una señal para alerta:
json
 
  
 
 
{
  "message": "Stock actualizado a 5",
  "data": { ... },
  "signal": {
    "type": "low_stock",
    "consumible_id": "550e8400-...",
    "stock": 5
  }
}
 
 

Auth: Admin únicamente
DELETE /consumibles/{id} — Eliminar
text
 
  
 
 
DELETE /consumibles/550e8400-e29b-41d4-a716-446655440000
 
 

Auth: Admin únicamente
Picking
GET /picking — Listar pickings
text
 
  
 
 
GET /picking
GET /picking?estado=en_progreso
GET /picking?asignado_a_mi=true
GET /picking?search=planta eléctrica
 
 
Parámetro
	
Tipo
	
Descripción
estado	query	borrador, asignado, en_progreso, completado, cancelado
asignado_a_mi	query bool	true para ver solo los del usuario actual
search	query	Busca en referencia y motivo
 
 

     

    Nota importante: Los técnicos (nivel 0) solo ven los pickings asignados a ellos automáticamente, sin necesidad de asignado_a_mi.

Respuesta (lista ligera con conteos):
json
 
  
 
 
{
  "data": [
    {
      "id": "uuid",
      "referencia": "Mantenimiento Planta XYZ",
      "motivo": "Revisión trimestral...",
      "estado": "en_progreso",
      "progreso": 60,
      "total_items": 10,
      "items_completados": 6,
      "personal_asignado": [
        { "id": "uuid", "nombre": "Juan Pérez", "cedula": "V-12345678" }
      ]
    }
  ]
}
 
 

Auth: Cualquier usuario activo
GET /picking/catalogo/buscar — Buscar en catálogo

Usado al crear un picking para buscar herramientas y consumibles:
text
 
  
 
 
GET /picking/catalogo/buscar?q=multimetro&tipo=herramienta
GET /picking/catalogo/buscar?q=cable
GET /picking/catalogo/buscar?q=aislante&tipo=consumible
 
 
Parámetro
	
Tipo
	
Descripción
q	query (requerido)	Término de búsqueda, mínimo 2 caracteres
tipo	query	herramienta o consumible (si se omite, busca en ambos)
 
 

Respuesta:
json
 
  
 
 
{
  "data": [
    {
      "type": "herramienta",
      "id": "uuid",
      "nombre": "Multímetro Digital Fluke",
      "detalle": "Fluke 117",
      "estado": "Disponible",
      "tipo": "Medición"
    },
    {
      "type": "consumible",
      "id": "uuid",
      "nombre": "Cable AWG 12",
      "detalle": "Cobre rojo",
      "estado": "Disponible",
      "stock": 100,
      "unidad": "metro"
    }
  ]
}
 
 

Auth: Cualquier usuario activo
POST /picking — Crear picking
text
 
  
 
 
POST /picking
 
 
json
 
  
 
 
{
  "referencia": "Mantenimiento Planta Eléctrica - Cliente XYZ",
  "motivo": "Revisión trimestral de planta eléctrica, se requieren herramientas de medición y consumibles de limpieza e impermeabilización",
  "personal_ids": [
    "uuid-del-tecnico-1",
    "uuid-del-tecnico-2"
  ],
  "items": [
    { "item_type": "herramienta", "item_id": "uuid-herramienta", "cantidad": 1 },
    { "item_type": "herramienta", "item_id": "uuid-herramienta-2", "cantidad": 2 },
    { "item_type": "consumible", "item_id": "uuid-consumible", "cantidad": 5 }
  ]
}
 
 
Campo
	
Tipo
	
Requerido
	
Descripción
referencia	string	Sí	Nombre/identificador del picking
motivo	string	Sí	Descripción detallada
personal_ids	uuid[]	No	Técnicos asignados
items	array	No	Herramientas y consumibles iniciales
items[].item_type	string	Sí	"herramienta" o "consumible"
items[].item_id	uuid	Sí	ID del item en su tabla
items[].cantidad	int	No	Default: 1
 
 

Comportamiento del estado:

     Sin personal asignado → borrador
     Con personal asignado → asignado

Auth: tipo_usuario >= 1
GET /picking/{id} — Ver picking completo
text
 
  
 
 
GET /picking/550e8400-e29b-41d4-a716-446655440000
 
 

Incluye todos los ítems con su estado individual:
json
 
  
 
 
{
  "data": {
    "id": "uuid",
    "referencia": "Mantenimiento Planta XYZ",
    "motivo": "...",
    "estado": "en_progreso",
    "progreso": 60,
    "creador_id": "uuid",
    "personal_asignado": [ ... ],
    "items": [
      {
        "id": "uuid",
        "item_type": "herramienta",
        "item_id": "uuid-herramienta",
        "nombre": "Multímetro Digital Fluke",
        "detalle": "Fluke 117",
        "estado": "tomado",
        "cantidad_solicitada": 1,
        "cantidad_tomada": 1,
        "agregado_por_tecnico": false,
        "notas": null
      },
      {
        "id": "uuid",
        "item_type": "consumible",
        "item_id": null,
        "nombre": "Cinta aislante 3M",
        "detalle": "Roll 18mm negro",
        "estado": "pendiente",
        "cantidad_solicitada": 3,
        "cantidad_tomada": 0,
        "agregado_por_tecnico": true,
        "notas": "Necesaria para aislar conexiones"
      }
    ]
  }
}
 
 

Auth: Creador, técnico asignado, o cualquier admin/moderador
PUT /picking/{id} — Actualizar picking

Actualización parcial del creador:
text
 
  
 
 
PUT /picking/550e8400-e29b-41d4-a716-446655440000
 
 
json
 
  
 
 
{
  "referencia": "Nuevo nombre (opcional)",
  "motivo": "Nuevo motivo (opcional)",
  "personal_ids": ["uuid-nuevo-tecnico-1", "uuid-nuevo-tecnico-2"]
}
 
 
Campo
	
Tipo
	
Descripción
referencia	string	Nuevo nombre
motivo	string	Nueva descripción
estado	string	Solo para cancelar ("cancelado")
personal_ids	uuid[]	Reemplaza toda la lista de asignados
 
 

     

    Si se agregan técnicos a un picking en borrador, el estado cambia a asignado automáticamente.

Auth: Creador o admin
DELETE /picking/{id} — Eliminar picking
text
 
  
 
 
DELETE /picking/550e8400-e29b-41d4-a716-446655440000
 
 

Solo se puede eliminar si está en borrador, cancelado o completado.

Auth: Admin únicamente (nivel >= 2)
Acciones del Técnico sobre Ítems
PATCH /picking/{picking_id}/items/{item_id}/estado — Marcar estado

El técnico cambia el estado de un ítem:
text
 
  
 
 
PATCH /picking/550e.../items/abc.../estado
 
 
json
 
  
 
 
{
  "estado": "tomado",
  "cantidad_tomada": 1,
  "notas": "En buen estado"
}
 
 
Campo
	
Tipo
	
Descripción
estado	string (requerido)	"tomado", "no_disponible", o "innecesario"
cantidad_tomada	int	Solo si estado = "tomado". Si se omite, usa cantidad_solicitada
notas	string	Comentario opcional
 
 

Efectos:

     Si el picking estaba en asignado → cambia a en_progreso
     Se recalcula el progreso del picking (0-100)
     La respuesta incluye signal para WebSocket

json
 
  
 
 
{
  "message": "Ítem marcado como 'tomado'",
  "data": { ... },
  "signal": {
    "type": "picking_update",
    "event": "item_estado_changed",
    "picking_id": "uuid",
    "detail": {
      "item_id": "uuid",
      "nuevo_estado": "tomado",
      "progreso": 33
    }
  }
}
 
 

Auth: Técnico asignado al picking (o creador/admin)
POST /picking/{picking_id}/items — Agregar ítem faltante

El técnico agrega algo que no estaba en la lista original:
text
 
  
 
 
POST /picking/550e.../items
 
 

Opción A — Desde el catálogo (con item_id):
json
 
  
 
 
{
  "item_type": "consumible",
  "item_id": "uuid-del-consumible-en-catalogo",
  "cantidad": 3,
  "notas": "Se necesita para sellar conexiones"
}
 
 

Opción B — Libre (sin item_id):
json
 
  
 
 
{
  "item_type": "consumible",
  "nombre": "Cinta aislante 3M",
  "detalle": "Roll 18mm negro",
  "cantidad": 3,
  "notas": "Necesaria para aislar conexiones"
}
 
 
Campo
	
Tipo
	
Requerido
	
Descripción
item_type	string	Sí	"herramienta" o "consumible"
item_id	uuid	No	Si existe en el catálogo
nombre	string	Sí si no hay item_id	Nombre del item
detalle	string	No	Descripción adicional
cantidad	int	No	Default: 1
notas	string	No	Comentario
 
 

El ítem se crea con agregado_por_tecnico: true.

Auth: Técnico asignado (o creador/admin)
DELETE /picking/{picking_id}/items/{item_id} — Quitar ítem
text
 
  
 
 
DELETE /picking/550e.../items/abc...
 
 

     Si agregado_por_tecnico = true → solo el técnico que lo agregó puede borrarlo
     Si agregado_por_tecnico = false → solo el creador o admin puede borrarlo

Auth: Según regla arriba
Acciones de Estado del Picking
POST /picking/{id}/completar — Completar
text
 
  
 
 
POST /picking/550e.../completar
 
 

Marca como completado con progreso 100. No requiere que todos los ítems estén marcados.

Auth: tipo_usuario >= 1
POST /picking/{id}/cancelar — Cancelar
text
 
  
 
 
POST /picking/550e.../cancelar
 
 

No se puede cancelar si ya está completado o cancelado.

Auth: tipo_usuario >= 1
Señales WebSocket (signal)

Varios endpoints incluyen un campo signal en la respuesta. Es un objeto con la estructura:
json
 
  
 
 
{
  "type": "picking_update",
  "event": "item_estado_changed | item_added_by_tecnico | item_deleted | picking_created | picking_updated | picking_completed | picking_cancelled",
  "picking_id": "uuid",
  "detail": {
    "progreso": 75,
    "item_id": "uuid",
    "nuevo_estado": "tomado"
  }
}
 
 

Están diseñadas para ser consumidas por un WebSocket futuro que notifique en tiempo real el avance del picking a los creadores y otros observadores.
Estados del Picking
text
 
  
 
 
borrador ──→ asignado ──→ en_progreso ──→ completado
    │              │            │
    └──────────────┴────────────┴──→ cancelado
 
 
Estado
	
Cuándo se asigna
borrador	Creación sin personal asignado
asignado	Creación con personal, o al agregar personal a un borrador
en_progreso	Un técnico cambia el estado de cualquier ítem, o agrega uno nuevo
completado	Manualmente vía POST /picking/{id}/completar
cancelado	Manualmente vía POST /picking/{id}/cancelar o PUT con estado: "cancelado"
 
 
Estados del Ítem
Estado
	
Significado
pendiente	Aún no procesado por el técnico
tomado	El técnico lo tomó del inventario
no_disponible	No existe en el inventario en este momento
innecesario	El técnico decidió que no hace falta para este picking
 
 
Permisos por Nivel
Endpoint
	
Técnico (0)
	
Moderador (1)
	
Admin (2+)
GET /consumibles	✅	✅	✅
POST/PUT/DELETE /consumibles	❌	❌	✅
GET /picking	solo propios	✅	✅
POST /picking	❌	✅	✅
PUT /picking/{id}	❌	solo propios	✅
DELETE /picking/{id}	❌	❌	✅
PATCH items/estado	solo asignados	✅	✅
POST items (agregar)	solo asignados	✅	✅
completar / cancelar	❌	✅	✅
```