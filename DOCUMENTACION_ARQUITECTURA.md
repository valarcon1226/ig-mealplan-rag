# Documentación y Arquitectura del Proyecto: AI Instagram Recipe Scraper

Este documento explica de manera detallada todo lo que hemos construido en este proyecto, cómo funciona la arquitectura por detrás, cuáles son las APIs que creamos y cómo se conectan las diferentes piezas. Esta documentación sirve como referencia técnica y funcional.

---

## 1. Arquitectura General del Sistema

El proyecto está dividido en dos partes principales (Frontend y Backend) que se comunican entre sí a través de Internet usando un túnel seguro (Ngrok). 

### A. Frontend (Interfaz de Usuario)
- **Dónde vive:** En Google AI Studio (entorno de desarrollo web en la nube, usando React/Vite).
- **Qué hace:** Es la aplicación visual que tú utilizas. Tiene pestañas como "Profile" (para configurar credenciales), "Add Recipe" (para ver los posts de Instagram y analizarlos) y "Cookbook" (tu recetario guardado).
- **Cómo se comunica:** Hace peticiones web (HTTP GET y POST) hacia la URL pública generada por Ngrok, que a su vez redirige esas peticiones a tu computadora.

### B. Backend (Servidor Local de Python)
- **Dónde vive:** Se ejecuta localmente en tu computadora usando **FastAPI**.
- **Qué hace:** Es el "cerebro" real de la aplicación. Se encarga de iniciar sesión en Instagram de forma invisible, descargar tus posts guardados, procesar los videos/imágenes, y enviárselos a la Inteligencia Artificial (Gemini) para extraer los datos.
- **Túnel (Ngrok):** Como el Frontend está en la nube de Google y el Backend en tu laptop (puerto `8011`), usamos **Ngrok** para crear un puente (ej. `https://xxx.ngrok-free.dev`) que permite que ambas partes hablen sin problemas de firewall.

---

## 2. Tecnologías y Librerías Utilizadas

1. **FastAPI (`ig_recetas.py`)**: El motor principal del servidor local. Crea los "Endpoints" o APIs a los que el Frontend llama.
2. **Instagrapi**: Una librería especial de Python que simula ser un celular conectándose a Instagram. Se usa para evadir las restricciones de Meta y poder extraer tus colecciones sin usar la API oficial restringida de Instagram.
3. **LangChain (`langchain_pipeline.py`)**: Un orquestador de Inteligencia Artificial. Se encarga de encadenar varios "pasos" lógicos para que la IA procese la información ordenadamente.
4. **Google Gemini API (`gemini-1.5-flash`)**: El modelo fundacional de IA que usamos. Es el encargado de ver los videos, leer las imágenes y entender las recetas.

---

## 3. Las APIs (Endpoints) que Creamos

El backend expone rutas específicas (APIs) a las que el Frontend llama. Cada ruta tiene una función clara:

### 1. `POST /login`
- **Para qué sirve:** Iniciar sesión en Instagram de forma silenciosa.
- **Cómo funciona:** Recibe tu usuario (`valarc0n`) y tu contraseña mediante "Headers" (encabezados ocultos). Utiliza *instagrapi* para hacer el login y guarda un archivo físico llamado `ig_session_valarc0n.json`. Este archivo guarda tu sesión (cookies) para no tener que iniciar sesión nuevamente y evitar bloqueos por parte de Instagram.

### 2. `GET /collections`
- **Para qué sirve:** Trae la lista de carpetas/colecciones que tienes guardadas en tu perfil de Instagram.
- **Cómo funciona:** Revisa que exista una sesión activa y le pide a Instagram (vía instagrapi) los nombres y IDs de tus colecciones (por ejemplo, la carpeta "Recetas").

### 3. `GET /collection-posts/all`
- **Para qué sirve:** Extrae todas las publicaciones (Reels o Fotos) que están dentro de una colección específica.
- **Cómo funciona:** El Frontend le envía el `collection_id` y el Backend devuelve una lista con la portada, el link y el texto (caption) de cada post.

### 4. `POST /analyze-langchain-by-id`
- **Para qué sirve:** Es el corazón de la inteligencia artificial. Analiza un post de Instagram y lo transforma en una receta estructurada con macros.
- **Cómo funciona paso a paso:**
  1. Recibe el `media_id` (el identificador único del video de Instagram).
  2. El Backend usa *instagrapi* para buscar la URL real de descarga de ese video o imagen, evadiendo bloqueos de la CDN de Instagram.
  3. Descarga el video internamente a tu computadora (con reintentos automáticos para evitar cortes de conexión, un error común que llamamos `IncompleteRead`).
  4. Le pasa el video descargado al archivo `langchain_pipeline.py` para hacer la magia con Gemini.

---

## 4. El Pipeline de Inteligencia Artificial (LangChain)

Cuando se llama a `/analyze-langchain-by-id`, el proceso interno en `langchain_pipeline.py` consta de 3 etapas secuenciales:

1. **Extracción (Extract Text from Media):**
   - Si es un video, se sube temporalmente a los servidores de Google usando la *Gemini Files API*. 
   - Se le dice a Gemini: *"Mira este video y lee la descripción. Dime paso a paso qué están cocinando y qué ingredientes usan"*.
   - Devuelve un texto "crudo".

2. **Estructuración (Structure Recipe):**
   - Toma el texto crudo del paso anterior y le pide a Gemini que lo formatee como un objeto JSON estricto.
   - Extrae el Título, Tiempo de preparación, Dificultad, Pasos (en lista) y una lista limpia de ingredientes con sus cantidades exactas (ej. "2 huevos", "100g de harina").

3. **Cálculo Nutricional (Calculate Nutrition):**
   - Toma la lista limpia de ingredientes y usa la IA como nutricionista. Calcula las calorías, proteínas, grasas y carbohidratos aproximados totales de la receta.
   - Si el usuario lo pidió en el Frontend, ajusta las porciones dinámicamente multiplicando los ingredientes.

---

## 5. Decisiones Claves de Diseño y Solución de Problemas

Durante el desarrollo, superamos varios obstáculos técnicos importantes:

- **Manejo de la API Key de Gemini:** Originalmente, el frontend pedía la llave. Para mayor seguridad y facilidad, quitamos esto y almacenamos la llave (`AIzaSy...`) de forma segura en un archivo oculto local llamado `.env`. El backend lee este archivo localmente sin exponer la llave en la web.
- **Bloqueos de IP en Instagram:** Al hacer muchas pruebas, Instagram bloqueaba la conexión temporalmente ("BadPassword"). Lo resolvimos manejando correctamente el archivo de sesión (`ig_session_valarc0n.json`) para que solo se haga login una sola vez.
- **Límites de Velocidad (429 Too Many Requests):** Cambiamos el modelo de Inteligencia Artificial de `gemini-2.0-flash-lite` a `gemini-1.5-flash`, ya que este último tiene un límite de cuota gratuita mucho más generoso, evitando que el sistema colapsara al analizar varias recetas seguidas.
- **Imágenes rotas en el Frontend:** Las portadas de los videos de Instagram no cargaban en la página web porque Meta bloquea sitios externos. Se solucionó agregando la propiedad `referrerPolicy="no-referrer"` en las imágenes del frontend.
- **Descargas Incompletas (`IncompleteRead`):** Los videos pesados de Instagram a veces cortaban la conexión a la mitad. Se solucionó agregando un sistema de reintentos (`retry logic`) en el código de descarga del backend.

---

## Resumen del Flujo Completo

1. Abres la app web (Frontend).
2. Haces login. El Frontend llama al Backend (`/login`), el Backend habla con Instagram.
3. Vas a "Add Recipe" y seleccionas tu carpeta. El Frontend llama al Backend (`/collections` y `/collection-posts/all`).
4. Le das clic a **"Analyze & Import"**.
5. El Frontend llama al Backend (`/analyze-langchain-by-id`).
6. El Backend descarga el video, lo procesa con la IA de Gemini en 3 pasos (Texto -> JSON -> Macros).
7. El Backend responde con la receta final.
8. El Frontend la dibuja en la pantalla y la guarda en tu **Cookbook**.
