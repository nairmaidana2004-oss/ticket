

# 🚀 **MANUAL COMPLETO – SISTEMA DE TICKETS EN ATIGRAVITY**

*(Con roles, pantallas y control administrativo)*

---

## 🧩 **ESTRUCTURA GENERAL DEL SISTEMA**

El sistema tendrá **3 tipos de pantallas** y **1 rol principal**:

### 📺 1. Pantalla TV (Sala de Espera)

➡ Solo visualización
➡ Se muestra en el televisor

### 🧍 2. Pantalla de Registro del Socio

➡ En la entrada
➡ El socio se registra y elige a dónde ir

### 🛠️ 3. Panel de Administrador

➡ Control total del sistema
➡ Llamar, finalizar, ver estadísticas

---

# 🔐 **ROL DEL SISTEMA**

## 👤 **ROL: ADMINISTRADOR**

Este rol es el **único con acceso interno** al sistema.

### El Administrador puede:

✔ Acceder a todas las pantallas
✔ Ver todos los tickets
✔ Llamar tickets
✔ Finalizar tickets
✔ Ver histórico
✔ Reiniciar numeraciones (opcional)
✔ Administrar departamentos

> ⚠️ **Los socios NO tienen usuario ni login**, solo interactúan con la pantalla de entrada.

---

# 🟦 1. **BASE DE DATOS (TABLAS)**

### ✔ Tabla: **departamentos**

| Campo  | Tipo         |
| ------ | ------------ |
| id     | autonumérico |
| nombre | texto        |
| codigo | texto corto  |

Datos iniciales:

| nombre            | codigo |
| ----------------- | ------ |
| Créditos          | C      |
| Atención al socio | A      |
| Tarjeta           | T      |
| Ahorros           | AH     |

---

### ✔ Tabla: **tickets**

| Campo           | Tipo         |
| --------------- | ------------ |
| id              | autonumérico |
| numero          | texto        |
| departamento_id | relación     |
| estado          | texto        |
| fecha_creacion  | fecha/hora   |
| fecha_atencion  | fecha/hora   |

**Estados permitidos**:

* Pendiente
* Llamado
* En atención
* Finalizado

---

# 🟩 2. **LÓGICA DE NUMERACIÓN AUTOMÁTICA**

📌 Se hace con **Flows de Atigravity** (sin código).

Formato:

```
C-001
A-002
T-010
AH-001
```

Cada departamento lleva **su propia secuencia**.

---

# 🟨 3. **PANTALLA 1 – REGISTRO DEL SOCIO (ENTRADA)**

📍 Ubicación: Entrada de la cooperativa
📍 Sin login

### 🎯 Objetivo:

Que el socio **seleccione el departamento** y obtenga su ticket.

---

### 🖥️ Componentes de la pantalla:

✔ Título: *“Seleccione el área a la que desea dirigirse”*
✔ Botones grandes:

* Créditos
* Atención al socio
* Tarjeta
* Ahorros

---

### 🔘 Acción de cada botón:

1. Ejecuta flujo **Crear Ticket**
2. Genera número automático
3. Guarda en estado **Pendiente**
4. Muestra:

   * Número de ticket
   * Departamento
   * Mensaje: *“Aguarde su turno”*
5. (Opcional) Imprime ticket en PDF

---

# 📺 4. **PANTALLA 2 – SALA DE ESPERA (TELEVISOR)**

📍 Pantalla SOLO VISUAL
📍 No editable
📍 Sin botones

---

### 🎯 Objetivo:

Mostrar a los socios **qué ticket está siendo llamado**.

---

### 🖥️ Contenido:

| Departamento | Ticket | Estado      |
| ------------ | ------ | ----------- |
| Créditos     | C-012  | En atención |
| Ahorros      | AH-005 | Llamado     |

---

### ⚙️ Configuración:

✔ Filtro: estado = “Llamado” o “En atención”
✔ Orden: fecha_atencion DESC
✔ Refresco automático cada 5 segundos
✔ Fuente grande (modo cartel)

---

# 🛠️ 5. **PANTALLA 3 – PANEL DEL ADMINISTRADOR**

📍 Acceso restringido
📍 Solo rol **Administrador**

---

### 🎯 Objetivo:

Gestionar completamente los tickets.

---

### 🖥️ Vista principal:

| Ticket | Departamento | Estado    | Acciones  |
| ------ | ------------ | --------- | --------- |
| C-010  | Créditos     | Pendiente | Llamar    |
| A-005  | Atención     | Pendiente | Llamar    |
| T-002  | Tarjeta      | Llamado   | Finalizar |

---

### 🔘 Acciones disponibles:

#### ✔ **Llamar**

* Estado → Llamado
* Registra fecha_atencion
* Aparece en TV

#### ✔ **Finalizar**

* Estado → Finalizado
* Sale de la pantalla TV

#### ✔ **Siguiente**

* Busca el siguiente ticket Pendiente del mismo departamento
* Lo llama automáticamente

---

# 🔄 6. **FLUJOS NECESARIOS EN ATIGRAVITY**

### 🔹 Flujo 1: Crear Ticket

(Ejecutado por el socio)

### 🔹 Flujo 2: Llamar Ticket

(Admin)

### 🔹 Flujo 3: Finalizar Ticket

(Admin)

### 🔹 Flujo 4: Siguiente Ticket

(Admin)

---

# 🧪 7. **PRUEBAS DEL SISTEMA**

✔ Registrar tickets desde entrada
✔ Verlos en panel admin
✔ Llamar ticket → aparece en TV
✔ Finalizar → desaparece
✔ Verificar numeración independiente por área

---

# ✅ 8. **CHECKLIST FINAL**

✔ Rol Administrador creado
✔ Pantalla Entrada (Socios)
✔ Pantalla TV (Sala de espera)
✔ Panel Administrador
✔ Tablas configuradas
✔ Flujos funcionando

---

## 📄 ¿QUERÉS QUE AHORA TE LO ENTREGUE COMO?

* ✅ **Manual en PDF**
* ✅ Paso a paso dentro de Atigravity
* ✅ Flujos detallados uno por uno
* ✅ Checklist para implementación en la cooperativa


