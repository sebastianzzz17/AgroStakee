# 🌱 AgroStake

**Proyecto desarrollado para el 🚀 NASA International Space Apps Challenge**

**Sistema integral de agricultura de precisión IoT + datos satelitales de la NASA para el diagnóstico de suelos y planificación inteligente de rotación de cultivos.**

🔗 **Demo en vivo:** [AgroStake](https://agrostakee-1.onrender.com/)

## 📖 Resumen del Proyecto

**AgroStake** es una solución creada para el **NASA Space Apps Challenge** que combina un sensor físico en forma de estaca inteligente con una plataforma web impulsada por datos aeroespaciales de observación terrestre de la NASA. Para abordar el desafío de la gestión sostenible de la tierra y la degradación de los suelos, nuestro sistema cruza las mediciones locales tomadas directamente en el terreno (humedad, temperatura, pH y nutrientes NPK) con variables climáticas históricas y actuales obtenidas vía satélite, además del historial de siembra y los objetivos productivos del agricultor.

Con esta información, la aplicación genera un plan de acción personalizado con recomendaciones de **rotación de 3 cultivos a lo largo de 3 temporadas consecutivas** y proyecta su impacto agronómico y productivo a futuro.

### ¿Por qué es importante?

AgroStake democratiza el acceso a datos aeroespaciales y agronómicos de grado científico, permitiendo a pequeños y medianos agricultores tomar decisiones basadas en evidencia sin necesidad de ser especialistas, evitando el desgaste por monocultivo, optimizando el uso de agua e insumos y maximizando la productividad de sus cosechas.

## ⚙️ ¿Cómo Funciona?

El sistema opera en tres etapas conectadas de extremo a extremo:

1. **Captura en campo (Hardware IoT):**
   La estaca se clava directamente en el lote para medir parámetros físico-químicos del suelo. Un microcontrolador **ESP32** procesa las lecturas provenientes de sensores industriales mediante protocolo **RS485**, respalda registros localmente y los transmite hacia la nube (vía MQTT en tiempo real o HTTP autenticado por token).

2. **Procesamiento y cruce de datos (Backend):**
   Un servidor desarrollado en **Python** recibe y valida la telemetría de la estaca, clasifica los niveles agronómicos y los integra mediante APIs con información meteorológica e histórica de satélites de la **NASA** (como **NASA POWER**).

3. **Análisis y visualización (Frontend):**
   La plataforma web cruza los datos del suelo y del clima con el cultivo previo y el objetivo del productor (por ejemplo: *maximizar rentabilidad, regenerar nitrógeno o ahorrar agua*) para calcular la rotación óptima de 3 temporadas, ofreciendo paneles interactivos, métricas en vivo y proyecciones a mediano y largo plazo.

## ✨ Beneficios Clave

* **Prevención de la degradación del suelo:** Evita el monocultivo intensivo alternando familias botánicas que fijan y consumen nutrientes de forma equilibrada.

* **Decisiones claras sin complejidad técnica:** Traduce telemetría industrial y variables satelitales en un plan de siembra paso a paso, bilingüe (Español / Inglés) y fácil de ejecutar.

* **Conectividad diseñada para zonas rurales:** Incorpora arquitectura de comunicación de largo alcance por radiofrecuencia/antena de fibra de vidrio y respaldo en memoria microSD para operar en fincas donde la conectividad es limitada.

* **Ahorro de costos e insumos:** Al conocer el estado real de humedad y nutrientes del suelo, se reduce el desperdicio de agua de riego y fertilizantes químicos.

## 🛠️ Arquitectura, Tecnologías y Componentes

### Software, Lenguajes y Fuentes de Datos

* **Backend & Motor Agronómico:** Python (API REST, gestión de estacas con autenticación por token SHA-256, integración MQTT en tiempo real y algoritmos de recomendación y proyección).

* **Frontend:** HTML5, CSS3 y JavaScript puro (interfaz responsiva tipo aplicación móvil/escritorio con visualización de telemetría en vivo).

* **Datos Satelitales:** APIs de observación terrestre y climatología histórica de la **NASA (NASA POWER)**.

* **Despliegue:** Plataforma cloud accesible en [AgroStake](https://agrostakee-1.onrender.com/)

### Hardware y Electrónica (Estaca y Nodo)

* **Microcontrolador:** ESP32.

* **Sensores y Bus Industrial:** Sensor multiparámetro de suelo (humedad, temperatura, pH, conductividad y NPK) + módulo convertidor **RS485 a UART TTL**.

* **Telecomunicaciones:** Módulo de radiofrecuencia y antena de fibra de vidrio para enlaces de largo alcance en campo.

* **Gestión de Energía:** Placa de carga y elevación a 5V, módulo elevador (*step-up*) a 12V para alimentación de sensores industriales y capacitores de filtrado de ruido eléctrico.

* **Interfaz Física y Respaldo:** Pantalla local, ranura para tarjeta **microSD** (registro offline), amplificador de audio y parlante para alertas y retroalimentación sonora en terreno.

## 🤖 Desarrollo Asistido por Inteligencia Artificial

Durante la conceptualización, diseño y construcción de **AgroStake** para el **NASA Space Apps Challenge**, utilizamos herramientas de Inteligencia Artificial como un copiloto técnico y de diseño en cada fase del proyecto:

1. **Suministro de ideas y contexto agronómico:**
   Le planteamos a las IAs nuestra visión central: conectar una estaca física con sensores de suelo reales y datos satelitales de la NASA para resolver un problema concreto del campo (la pérdida de fertilidad por falta de rotación de cultivos). Suministramos las restricciones reales del hardware (protocolo RS485, alimentación de 12V, conectividad intermitente en zonas rurales) y los objetivos que busca un agricultor en campo.

2. **Arquitectura de software e integración de datos:**
   Con base en nuestras ideas y requerimientos, las IAs nos apoyaron estructurando la comunicación entre el microcontrolador ESP32, el servidor en Python (endpoints HTTP con tokens de seguridad y suscripción MQTT en vivo) y el cruce de variables con fuentes climáticas satelitales de la NASA.

3. **Prototipado de interfaz y experiencia de usuario (UX/UI):**
   Iteramos junto con la IA el diseño de la interfaz web para que fuera clara, responsiva y usable tanto en computadores como en teléfonos móviles directamente en el cultivo, integrando paneles visuales de telemetría en vivo y tarjetas de recomendación comprensibles.


## 🎯 Visión a Futuro

Buscamos empoderar a pequeños y medianos agricultores con tecnología accesible de grado científico para hacer su producción más resiliente y rentable. A mediano plazo, proyectamos validar los modelos de rotación con datos de cosechas locales reales para consolidar a **AgroStake** como un estándar de asistencia técnica digital que frene la erosión de tierras cultivables y promueva prácticas agrícolas regenerativas.