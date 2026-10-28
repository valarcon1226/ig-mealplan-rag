import express from "express";
import path from "path";
import fs from "fs";
import multer from "multer";
import { createServer as createViteServer } from "vite";
import { GoogleGenAI } from "@google/genai";
import dotenv from "dotenv";

dotenv.config();

const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });
const upload = multer({ dest: '/tmp/' });
// ig-scrapp FastAPI backend. Not 8001: that port is taken by another local project's Docker API.
const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8011";

async function startServer() {
  const app = express();
  const PORT = 4000;

  app.use(express.json({ limit: '15mb' })); // receipt photos arrive as base64

  // Recipe thumbnails are served by the backend; stored as relative /static/... URLs.
  app.get('/static/*', async (req, res) => {
    try {
      const r = await fetch(`${BACKEND_URL}${req.path}`);
      if (!r.ok) return res.sendStatus(r.status);
      res.type(r.headers.get('content-type') || 'application/octet-stream');
      res.send(Buffer.from(await r.arrayBuffer()));
    } catch {
      res.sendStatus(502);
    }
  });

  // --- Garmin Connect API Routes ---

  app.post("/api/garmin/login", async (req, res) => {
    try {
      const { username, password } = req.body;
      const { GarminConnect } = await import("garmin-connect");
      
      const gc = new GarminConnect({ username, password });
      await gc.login();
      
      const profile = await gc.getUserProfile();
      
      res.json({ success: true, displayName: profile.displayName });
    } catch (err: any) {
      console.error("Garmin Login Error:", err);
      res.status(401).json({ error: err.message || "Failed to login to Garmin" });
    }
  });

  app.post("/api/garmin/calories", async (req, res) => {
    try {
      const { username, password, date } = req.body; // YYYY-MM-DD
      if (!username || !password) return res.status(400).json({ error: "Missing Garmin credentials" });
      
      const { GarminConnect } = await import("garmin-connect");
      const gc = new GarminConnect({ username, password });
      await gc.login();
      
      const profile = await gc.getUserProfile();
      // Use internal .get method to fetch the summary
      const summaryUrl = `https://connect.garmin.com/usersummary-service/usersummary/daily/${profile.displayName}?calendarDate=${date}`;
      const summary = await gc.get(summaryUrl);
      
      res.json({ summary });
    } catch (err: any) {
      console.error("Garmin Calories Error:", err);
      res.status(500).json({ error: err.message || "Failed to fetch Garmin calorie summary" });
    }
  });

  // --- Instagram API Routes ---

  app.get("/api/recipes", async (req, res) => {
    try {
      const vpsUrl = BACKEND_URL;
      const response = await fetch(`${vpsUrl}/api/recipes`, {
        method: "GET",
        headers: {
          "ngrok-skip-browser-warning": "true"
        }
      });
      if (!response.ok) {
        throw new Error("Failed to reach FastAPI server on VPS.");
      }
      const data = await response.json();
      return res.json(data);
    } catch (error: any) {
      console.error("Recipes Error:", error);
      res.status(500).json({ error: "Failed to fetch recipes: " + error.message });
    }
  });

  app.post("/api/recipes/search", async (req, res) => {
    try {
      const vpsUrl = BACKEND_URL;
      const response = await fetch(`${vpsUrl}/api/recipes/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "ngrok-skip-browser-warning": "true" },
        body: JSON.stringify(req.body)
      });
      const data = await response.json();
      res.status(response.status).json(data);
    } catch (error: any) {
      res.status(500).json({ error: "Failed to search recipes: " + error.message });
    }
  });

  // Bulk import of saved posts from Instagram's official data export (no account login).
  app.post("/api/import/instagram-export", async (req, res) => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/import/instagram-export`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "ngrok-skip-browser-warning": "true" },
        body: JSON.stringify(req.body)
      });
      res.status(response.status).json(await response.json());
    } catch (error: any) {
      res.status(500).json({ error: "Failed to import export: " + error.message });
    }
  });

  app.get("/api/import/saved", async (_req, res) => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/import/saved`, { headers: { "ngrok-skip-browser-warning": "true" } });
      res.status(response.status).json(await response.json());
    } catch (error: any) {
      res.status(500).json({ error: "Failed to load saved imports: " + error.message });
    }
  });

  app.post("/api/mealplan/from-pantry", async (req, res) => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/mealplan/from-pantry`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "ngrok-skip-browser-warning": "true" },
        body: JSON.stringify(req.body)
      });
      res.status(response.status).json(await response.json());
    } catch (error: any) {
      res.status(500).json({ error: "Failed to plan from pantry: " + error.message });
    }
  });

  app.post("/api/mealplan/generate", async (req, res) => {
    try {
      const vpsUrl = BACKEND_URL;
      const response = await fetch(`${vpsUrl}/api/mealplan/generate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "ngrok-skip-browser-warning": "true"
        },
        body: JSON.stringify(req.body)
      });
      // Pass the backend's status and message through (e.g. "no recipes fit your diet").
      const data = await response.json();
      return res.status(response.status).json(data);
    } catch (error: any) {
      console.error("Mealplan Error:", error);
      res.status(500).json({ error: "Failed to generate plan: " + error.message });
    }
  });

  app.post("/api/mealprep/generate", async (req, res) => {
    try {
      const vpsUrl = BACKEND_URL;
      const response = await fetch(`${vpsUrl}/api/mealprep/generate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "ngrok-skip-browser-warning": "true"
        },
        body: JSON.stringify(req.body)
      });
      const data = await response.json();
      res.status(response.status).json(data);
    } catch (error: any) {
      console.error("Mealprep Error:", error);
      res.status(500).json({ error: "Failed to generate mealprep: " + error.message });
    }
  });

  app.post("/api/analyze-recipe", upload.single('media'), async (req, res) => {
    let uploadedFile: any = null;
    try {
      const { text } = req.body;
      const media = req.file;

      if (!text && !media) {
        return res.status(400).json({ error: "No text or media provided" });
      }

      const contents: any[] = [];
      
      if (media) {
         uploadedFile = await ai.files.upload({
           file: media.path,
         });
         contents.push(uploadedFile);
      }

      const prompt = `Analyze the provided recipe (video, image, or text) and extract the details in valid JSON format.
        Pay close attention to any spoken audio inside the video if provided, as well as the text caption.
        Do NOT output markdown. Just raw JSON.
        Format required:
        {
          "title": "string",
          "ingredients": [ { "name": "string", "amount": "string" } ],
          "instructions": ["string"],
          "servings": number,
          "macros": {
            "calories": number,
            "protein": number, // in grams
            "carbs": number, // in grams
            "fat": number, // in grams
            "fiber": number, // in grams
            "sugar": number // in grams
          },
          "categories": ["string"] // Exhaustive descriptive tags: e.g. "breakfast", "lunch", "dinner", "snack", "dessert", "drink", "chicken", "beef", "vegan", "high-protein", "low-carb"
        }
        
        Text caption / notes:
        ${text || "None provided"}
        `;

      contents.push(prompt);

      const response = await ai.models.generateContent({
        model: "gemini-2.5-flash",
        contents: contents,
      });

      const rawText = response.text || "";
      const jsonStr = rawText.replace(/```json/g, "").replace(/```/g, "").trim();
      const data = JSON.parse(jsonStr);

      res.json(data);
    } catch (error) {
      console.error("Error analyzing recipe:", error);
      res.status(500).json({ error: "Failed to analyze recipe" });
    } finally {
      if (req.file && fs.existsSync(req.file.path)) {
        fs.unlinkSync(req.file.path);
      }
      if (uploadedFile) {
        // Technically we can delete the file from the Google GenAI server too
        try {
           await ai.files.delete({ name: uploadedFile.name });
        } catch(e) {}
      }
    }
  });

  app.post("/api/generate-plan", async (req, res) => {
    try {
      const { preferences, recipes } = req.body;
      
      const response = await ai.models.generateContent({
        model: "gemini-2.5-flash",
        contents: `Given the following user preferences and a list of available recipes, generate a weekly meal plan and a grocery list.
        User Preferences: ${JSON.stringify(preferences)}
        Available Recipes: ${JSON.stringify(recipes.map((r: any) => ({id: r.id, title: r.title, macros: r.macros})))}
        
        Output raw JSON (no markdown) in the following format:
        {
          "mealPlan": [
            { "day": "Monday", "meals": [{ "type": "Breakfast", "recipeId": "string or null if suggesting general idea", "suggestion": "string" }] }
          ],
          "groceryList": ["string"]
        }`,
      });

      const rawText = response.text || "";
      const jsonStr = rawText.replace(/```json/g, "").replace(/```/g, "").trim();
      const data = JSON.parse(jsonStr);

      res.json(data);
    } catch (error) {
      console.error("Error generating plan:", error);
      res.status(500).json({ error: "Failed to generate plan" });
    }
  });

  // --- Pantry & Grocery List (backend routes keep the /api prefix, so they
  // need an explicit passthrough here too - the generic proxy below strips it) ---

  app.get("/api/pantry", async (req, res) => {
    try {
      const vpsUrl = BACKEND_URL;
      const response = await fetch(`${vpsUrl}/api/pantry`, {
        headers: { "ngrok-skip-browser-warning": "true" }
      });
      const data = await response.json();
      res.status(response.status).json(data);
    } catch (error: any) {
      res.status(500).json({ error: "Failed to fetch pantry: " + error.message });
    }
  });

  app.post("/api/pantry", async (req, res) => {
    try {
      const vpsUrl = BACKEND_URL;
      const response = await fetch(`${vpsUrl}/api/pantry`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "ngrok-skip-browser-warning": "true" },
        body: JSON.stringify(req.body)
      });
      const data = await response.json();
      res.status(response.status).json(data);
    } catch (error: any) {
      res.status(500).json({ error: "Failed to add pantry item: " + error.message });
    }
  });

  app.post("/api/pantry/remove", async (req, res) => {
    try {
      const vpsUrl = BACKEND_URL;
      const response = await fetch(`${vpsUrl}/api/pantry/remove`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "ngrok-skip-browser-warning": "true" },
        body: JSON.stringify(req.body)
      });
      const data = await response.json();
      res.status(response.status).json(data);
    } catch (error: any) {
      res.status(500).json({ error: "Failed to remove pantry item: " + error.message });
    }
  });

  app.post("/api/pantry/receipt", async (req, res) => {
    try {
      const vpsUrl = BACKEND_URL;
      const response = await fetch(`${vpsUrl}/api/pantry/receipt`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "ngrok-skip-browser-warning": "true" },
        body: JSON.stringify(req.body)
      });
      const data = await response.json();
      res.status(response.status).json(data);
    } catch (error: any) {
      res.status(500).json({ error: "Failed to scan receipt: " + error.message });
    }
  });

  app.delete("/api/pantry/:id", async (req, res) => {
    try {
      const vpsUrl = BACKEND_URL;
      const response = await fetch(`${vpsUrl}/api/pantry/${req.params.id}`, {
        method: "DELETE",
        headers: { "ngrok-skip-browser-warning": "true" }
      });
      const data = await response.json();
      res.status(response.status).json(data);
    } catch (error: any) {
      res.status(500).json({ error: "Failed to delete pantry item: " + error.message });
    }
  });

  app.post("/api/grocery/generate", async (req, res) => {
    try {
      const vpsUrl = BACKEND_URL;
      const response = await fetch(`${vpsUrl}/api/grocery/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "ngrok-skip-browser-warning": "true" },
        body: JSON.stringify(req.body)
      });
      const data = await response.json();
      res.status(response.status).json(data);
    } catch (error: any) {
      res.status(500).json({ error: "Failed to generate grocery list: " + error.message });
    }
  });

  app.post("/api/send-webhook", async (req, res) => {
    try {
      const { webhookUrl, data } = req.body;
      if (!webhookUrl) return res.status(400).json({ error: "No URL provided" });

      const fRes = await fetch(webhookUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      });
      res.json({ success: fRes.ok });
    } catch (e) {
      res.status(500).json({ error: "Failed to send data" });
    }
  });


  // --- API Proxy for FastAPI Backend ---
  app.all('/api/*', async (req, res, next) => {
    // We want to skip this generic proxy if a specific route like /api/garmin/... matches,
    // but Express executes in order. We should put this LAST for /api/*, or we can just 
    // manually skip the ones handled above. Since it's placed after specific /api/ routes,
    // Express will match the ones above first IF they are explicitly defined.
    // Wait, let's just make sure it's placed after standard endpoints.
    
    // Some routes like /api/analyze-recipe (Gemini) are handled above.
    const internalRoutes = [
      '/api/garmin/login',
      '/api/garmin/calories',
      '/api/analyze-recipe',
      '/api/generate-plan',
      '/api/send-webhook'
    ];
    if (internalRoutes.includes(req.path)) {
      return next(); // pass control to the next applicable route
    }

    const targetPath = req.path.replace('/api', '');
    const url = `${BACKEND_URL}${targetPath}${req.url.includes('?') ? '?' + req.url.split('?')[1] : ''}`;

    const headers: Record<string, string> = {
      'ngrok-skip-browser-warning': 'true',
      'Content-Type': 'application/json',
    };
    if (req.headers.authorization) headers.Authorization = req.headers.authorization;

    const fetchOptions: any = {
      method: req.method,
      headers,
    };

    if (req.method !== 'GET' && req.method !== 'HEAD') {
      fetchOptions.body = JSON.stringify(req.body);
    }

    try {
      const response = await fetch(url, fetchOptions);
      const data = await response.json().catch(() => ({}));
      res.status(response.status).json(data);
    } catch (err) {
      console.error("Proxy error:", err);
      res.status(500).json({ error: 'Proxy error connecting to backend' });
    }
  });

  // --- Vite Middleware ---
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  const server = app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
  
  // Increase timeouts for long-running Gemini API requests
  server.keepAliveTimeout = 300000;
  server.headersTimeout = 305000;
}

startServer();
