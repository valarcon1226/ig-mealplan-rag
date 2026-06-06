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

async function startServer() {
  const app = express();
  const PORT = 3000;

  app.use(express.json());

  // --- Garmin Connect API Routes ---

  app.post("/api/garmin/login", async (req, res) => {
    try {
      const { username, password } = req.body;
      const { GarminConnect } = await import("garmin-connect");
      
      const gc = new GarminConnect();
      await gc.login(username, password);
      
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
      const gc = new GarminConnect();
      await gc.login(username, password);
      
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

  app.post("/api/ig/proxy", async (req, res) => {
    try {
      const { url } = req.body;
      if (!url) return res.status(400).json({ error: "Missing url" });
      
      const fetchUrl = url.endsWith('/collections') ? url : url.replace(/\/$/, '') + '/collections';
      
      const ngrokRes = await fetch(fetchUrl, {
         method: 'GET',
         headers: { 'ngrok-skip-browser-warning': 'true' }
      });
      
      const data = await ngrokRes.json();
      res.json(data);
    } catch (e: any) {
      console.error("Ngrok Proxy Error:", e);
      res.status(500).json({ error: e.message });
    }
  });

  app.post("/api/ig/login", async (req, res) => {
    try {
      const vpsUrl = "http://127.0.0.1:8001";
      const { username, password } = req.body;
      const response = await fetch(`${vpsUrl}/login`, {
        method: "POST",
        headers: {
          "X-IG-Username": username,
          "X-IG-Password": password,
          "ngrok-skip-browser-warning": "true"
        }
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        let errMsg = errorData.detail || "Could not authenticate with backend.";
        if (typeof errMsg === 'string' && (errMsg.toLowerCase().includes('challenge') || errMsg.toLowerCase().includes('requerida'))) {
          errMsg = "Instagram requires verification or the credentials are incorrect. Please check them.";
        }
        return res.status(401).json({ error: errMsg });
      }
      
      res.json({ session: username });
    } catch (error: any) {
      console.error("VPS connection test error:", error);
      res.status(500).json({ error: "Failed to connect to backend server. Please try again later." });
    }
  });

  app.post("/api/ig/collections", async (req, res) => {
    try {
      const { username, password } = req.body;
      const vpsUrl = "http://127.0.0.1:8001";
      const response = await fetch(`${vpsUrl}/collections`, {
        method: "GET",
        headers: {
          "X-IG-Username": username,
          "X-IG-Password": password,
          "ngrok-skip-browser-warning": "true"
        }
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || "Failed to reach FastAPI server on VPS.");
      }
      const data = await response.json();
      return res.json({ collections: data.collections || data });
    } catch (error: any) {
      console.error("IG Collections Error:", error);
      res.status(500).json({ error: "Failed to fetch collections: " + error.message });
    }
  });

  app.post("/api/ig/scrape-collection", async (req, res) => {
    try {
      const { folderId, username, password } = req.body;
      const vpsUrl = "http://127.0.0.1:8001";
      
      const url = folderId 
          ? `${vpsUrl}/collection-posts/all?collection_id=${folderId}&since=0`
          : `${vpsUrl}/saved-posts?limit=20`;
          
      const response = await fetch(url, {
        method: "GET",
        headers: {
          "X-IG-Username": username,
          "X-IG-Password": password,
          "ngrok-skip-browser-warning": "true"
        }
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || "Failed to reach FastAPI server on VPS.");
      }
      const data = await response.json();
      
      let posts = Array.isArray(data) ? data : (data.posts || data.items || []);
      
      // Map from FastAPI custom format
      const scraped = posts.map((item: any) => {
        const post = item.media || item;
        return {
          id: post.id || post.pk || crypto.randomUUID(),
          caption: post.caption?.text || post.caption || "",
          imageUrl: post.image_versions2?.candidates?.[0]?.url || post.thumbnail_url || "",
          videoUrl: post.video_versions?.[0]?.url || post.video_url || "",
        };
      });
      return res.json({ items: scraped });
    } catch (error: any) {
      console.error("IG Scrape Error:", error);
      res.status(500).json({ error: "Failed to scrape collection: " + error.message });
    }
  });

  // --- API Routes ---

  app.get("/api/recipes", async (req, res) => {
    try {
      const vpsUrl = "http://127.0.0.1:8001";
      const response = await fetch(`${vpsUrl}/recipes`, {
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

  app.post("/api/analyze-langchain-by-id", async (req, res) => {
    try {
      const vpsUrl = "http://127.0.0.1:8001";
      const bodyParams = { ...req.body };
      // Fallback for post_id logic just in case
      if (bodyParams.post_id && !bodyParams.media_id) {
        bodyParams.media_id = bodyParams.post_id;
      }
      
      const response = await fetch(`${vpsUrl}/analyze-langchain-by-id`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "ngrok-skip-browser-warning": "true"
        },
        body: JSON.stringify(bodyParams)
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || errorData.error || "Failed to reach FastAPI server on VPS.");
      }
      const data = await response.json();
      return res.json(data);
    } catch (error: any) {
      console.error("IG Analyze Error:", error);
      res.status(500).json({ error: "Failed to analyze post: " + error.message });
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

    const BACKEND_URL = 'http://127.0.0.1:8001';
    const targetPath = req.path.replace('/api', '');
    const url = `${BACKEND_URL}${targetPath}${req.url.includes('?') ? '?' + req.url.split('?')[1] : ''}`;

    const headers: Record<string, string> = {
      'ngrok-skip-browser-warning': 'true',
      'Content-Type': 'application/json',
    };

    // Pasar headers de Instagram si vienen del frontend
    if (req.headers['x-ig-username']) headers['X-IG-Username'] = req.headers['x-ig-username'] as string;
    if (req.headers['x-ig-password']) headers['X-IG-Password'] = req.headers['x-ig-password'] as string;

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

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
}

startServer();
