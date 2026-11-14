// Copia este archivo como "secretos.h" (en la misma carpeta) y llena tus datos.
// secretos.h NO se debe subir a GitHub ni compartir: lleva la clave del WiFi y el token de tu estaca.
#pragma once

#define WIFI_SSID      "nombre-de-tu-wifi"
#define WIFI_CLAVE     "clave-de-tu-wifi"

// Dirección del servidor de Rotación Caribe + /api/estaca/lecturas
// En la app: Configuración > Mis estacas > Agregar, ahí aparece la dirección exacta.
#define SERVIDOR_URL   "https://tu-servidor.ejemplo.co/api/estaca/lecturas"

// Token que muestra la app UNA sola vez al crear la estaca (empieza por "est_").
#define ESTACA_TOKEN   "est_pega_aqui_tu_token"

// Certificado raíz (CA) del servidor, en formato PEM, para verificar HTTPS.
// Si lo dejas vacío, la conexión HTTPS queda cifrada pero SIN verificar el servidor (solo para pruebas).
#define CA_RAIZ ""
