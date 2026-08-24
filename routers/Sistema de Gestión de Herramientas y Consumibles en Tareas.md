📋 Sistema de Gestión de Herramientas y Consumibles en Tareas
📖 Descripción General

Este sistema permite gestionar el estado de las herramientas y consumibles asignados a una tarea a lo largo de su ciclo de vida. Proporciona trazabilidad, control de inventario y flexibilidad para adaptarse a cambios durante la ejecución de la tarea.
🔄 Estados disponibles
Herramientas
Estado	Descripción
asignada	La herramienta está planificada para la tarea pero aún no ha sido retirada.
en_uso	La herramienta ha sido retirada y está siendo utilizada en la tarea.
devuelta	La herramienta ha regresado y está disponible nuevamente.
Consumibles
Estado	Descripción
asignado	El consumible está planificado para la tarea pero aún no ha sido retirado.
en_uso	El consumible está siendo utilizado en la tarea.
consumido	El consumible ha sido utilizado completamente y no está disponible.
🏗️ Flujo de trabajo típico
1. Creación de la tarea

    Se asignan herramientas y consumibles mediante los campos herramienta_ids y consumible_ids.

    Al crear la tarea, automáticamente se crean registros de estado para cada herramienta y consumible con estado inicial "asignada" / "asignado".

    La tabla intermedia tarea_herramienta_estado / tarea_consumible_estado almacena el historial de cambios.

2. Inicio de la tarea (opcional)

    Endpoint: POST /tareas/{tarea_id}/iniciar

    Función: Cambia el estado de todas las herramientas y consumibles asignados a la tarea a "en_uso" (o "en_uso" para herramientas y "en_uso" para consumibles) en un solo paso.

    Uso típico: Cuando el equipo comienza a trabajar en la tarea y retira todo el material de una vez.

3. Cambio de estado individual

    Endpoint: PATCH /tareas/{tarea_id}/herramientas/{herramienta_id}/estado

    Endpoint: PATCH /tareas/{tarea_id}/consumibles/{consumible_id}/estado

    Función: Cambia el estado de una herramienta o consumible específico.

    Uso típico: Cuando una herramienta se devuelve antes de que finalice la tarea (porque ya no se necesita) o se retira una herramienta adicional durante la ejecución.

4. Consulta de estados actuales

    Endpoint: GET /tareas/{tarea_id}/herramientas-estado

    Endpoint: GET /tareas/{tarea_id}/consumibles-estado

    Función: Obtiene el estado actual de todas las herramientas o consumibles asignados a una tarea.

    Uso típico: Para mostrar en la interfaz de usuario el estado en tiempo real.

5. Finalización de la tarea

    No hay un endpoint específico para "finalizar" herramientas; se espera que el usuario marque cada herramienta como "devuelta" y cada consumible como "consumido" individualmente.

    También se puede usar el flujo de pasos de la tarea para indicar el avance general.

🔌 Endpoints API
Herramientas
GET /tareas/{tarea_id}/herramientas-estado

Obtiene el estado de todas las herramientas asignadas a la tarea.

Respuesta:
json

{
  "status": "success",
  "data": [
    {
      "id": "uuid",
      "tarea_id": "uuid",
      "herramienta_id": "uuid",
      "estado": "en_uso",
      "fecha_inicio": "2026-08-23T10:00:00Z",
      "fecha_fin": null,
      "observaciones": "En uso desde las 10:00",
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}

PATCH /tareas/{tarea_id}/herramientas/{herramienta_id}/estado

Cambia el estado de una herramienta específica.

Cuerpo:
json

{
  "estado": "devuelta",
  "personal_id": "uuid-del-personal-que-devolvio",
  "observaciones": "Herramienta devuelta en buen estado"
}

POST /tareas/{tarea_id}/iniciar

Cambia todas las herramientas a "en_uso".

Respuesta:
json

{
  "status": "success",
  "message": "Tarea iniciada. 5 herramienta(s) marcadas como 'en_uso'",
  "data": {
    "herramientas_actualizadas": 5
  }
}

Consumibles
GET /tareas/{tarea_id}/consumibles-estado

Obtiene el estado de todos los consumibles asignados a la tarea.
PATCH /tareas/{tarea_id}/consumibles/{consumible_id}/estado

Cambia el estado de un consumible específico.

Cuerpo:
json

{
  "estado": "consumido",
  "personal_id": "uuid-del-personal-que-lo-uso",
  "observaciones": "Se utilizó todo el rollo de cinta"
}

🖥️ Interfaz de usuario (Frontend)
Tab "Recursos" (recursos.dart)

Visualización:

    Cada herramienta/consumible se muestra como una tarjeta con:

        Icono indicador de estado (color):

            🟡 Naranja → en_uso

            🟢 Verde → devuelta / consumido

            ⚪ Gris → asignada / asignado

        Nombre del elemento

        Estado actual (texto)

        Observaciones (si existen)

    Menú desplegable (PopupMenuButton):

        Opciones:

            Reasignar → vuelve a "asignada"

            Marcar en uso → cambia a "en_uso"

            Marcar devuelta → cambia a "devuelta" (herramientas)

            Marcar consumido → cambia a "consumido" (consumibles)

Botón "Iniciar tarea":

    Un botón en la parte superior de la pestaña que llama al endpoint POST /tareas/{tarea_id}/iniciar.

    Cambia todas las herramientas a "en_uso" de una vez.

Actualización en tiempo real:

    Al cambiar el estado, la interfaz se actualiza automáticamente sin recargar la página, gracias al setState local y la recarga de datos desde el API.

📝 Ejemplos de uso práctico
Escenario 1: Tarea de mantenimiento de un día

    Creación de la tarea → se asignan 5 herramientas.

    Inicio de la tarea → se hace clic en "Iniciar tarea", todas las herramientas pasan a "en_uso".

    Durante el día → se devuelven 2 herramientas (se cambian a "devuelta" manualmente).

    Fin del día → se devuelven las 3 herramientas restantes y se marcan como "devuelta".

    La tarea se completa (los pasos se marcan como completados).

Escenario 2: Tarea de varios días

    Creación de la tarea → se asignan 10 herramientas.

    Día 1 → se retiran 3 herramientas (se marcan "en_uso" individualmente).

    Día 2 → se retiran 3 herramientas más, y se devuelven 2 del día anterior (se cambian a "devuelta").

    Día 3 → se retiran las 4 herramientas restantes.

    Día 4 → se devuelven todas las herramientas y se marcan como "devuelta".

    La tarea se completa (pasos marcados como completados).

🗂️ Estructura de datos
Tabla: tarea_herramienta_estado
Campo	Tipo	Descripción
id	UUID	Clave primaria
tarea_id	UUID	FK a tareas.id
herramienta_id	UUID	FK a herramientas.id
personal_id	UUID	FK a personals.id (opcional)
estado	String	asignada, en_uso, devuelta
fecha_inicio	DateTime	Cuándo se marcó como "en_uso" (o creada)
fecha_fin	DateTime	Cuándo se marcó como "devuelta"
observaciones	Text	Notas adicionales (opcional)
created_at	DateTime	Fecha de creación del registro
updated_at	DateTime	Fecha de última actualización
Tabla: tarea_consumible_estado
Campo	Tipo	Descripción
id	UUID	Clave primaria
tarea_id	UUID	FK a tareas.id
consumible_id	UUID	FK a consumibles.id
personal_id	UUID	FK a personals.id (opcional)
estado	String	asignado, en_uso, consumido
fecha_inicio	DateTime	Cuándo se marcó como "en_uso" (o creada)
fecha_fin	DateTime	Cuándo se marcó como "consumido"
observaciones	Text	Notas adicionales (opcional)
created_at	DateTime	Fecha de creación del registro
updated_at	DateTime	Fecha de última actualización
🔐 Permisos

    Cualquier usuario autenticado puede consultar los estados (GET endpoints).

    Solo el creador de la tarea o usuarios con nivel >= 1 pueden modificar estados (PATCH endpoints) y usar el endpoint de inicio.

    Usuarios con nivel 0 (técnicos) solo pueden modificar estados si están asignados a la tarea o si tienen permisos especiales (se puede configurar en el backend).

⚠️ Consideraciones de inventario

    Marcar una herramienta como "devuelta" no actualiza automáticamente el estado de inventario (herramientas.estado). Esto se hace para evitar conflictos con otros sistemas (picking, préstamos, etc.). Se recomienda que el estado de inventario se gestione por separado.

    Marcar un consumible como "consumido" no descuenta automáticamente del stock (consumibles.stock_actual). Se puede integrar manualmente o mediante un proceso batch.

    Registro de auditoría completo: cada cambio de estado queda registrado con fecha y, opcionalmente, el personal que lo realizó.

🧪 Pruebas sugeridas

    Crear una tarea y verificar que los registros de estado se crean automáticamente.

    Iniciar la tarea y comprobar que todas las herramientas pasan a "en_uso".

    Cambiar el estado de una herramienta a "devuelta" y verificar que se actualiza la fecha_fin.

    Cambiar el estado de un consumible a "consumido" y verificar que se actualiza la fecha_fin.

    Consultar estados desde la API y desde la interfaz de usuario.

    Intentar cambiar el estado de una herramienta no asignada → debe devolver error 422.

📚 Recursos adicionales

    Backend: routers/tareas.py

    Modelos: models.py (clases TareaHerramientaEstado, TareaConsumibleEstado)

    Esquemas: schemas.py (clases HerramientaEstadoOut, ConsumibleEstadoOut, TareaHerramientaEstadoUpdate, TareaConsumibleEstadoUpdate)

    Frontend: lib/views/tarea_detail_view/recursos.dart

    API Service: lib/services/api_service.dart (métodos getHerramientasEstado, updateHerramientaEstado, getConsumiblesEstado, updateConsumibleEstado)

Documentación generada: 2026-08-23
Versión: 1.0