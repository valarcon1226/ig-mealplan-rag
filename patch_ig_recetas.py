import re

with open('backend/ig_recetas.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove the first finally block
old_finally = """    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error subiendo a Gemini: {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)"""
new_finally = """    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error subiendo a Gemini: {str(e)}")"""
content = content.replace(old_finally, new_finally)

# 2. Update the prompt
old_task = '"Analiza el video para extraer entidades culinarias específicas (nombre, ingredientes, tiempo, porciones, instrucciones). "'
new_task = '"Analiza el video para extraer entidades culinarias específicas (nombre, ingredientes, tiempo, porciones, instrucciones). También, identifica en qué segundo (timestamp en formato decimal, ej 3.5) se ve el plato terminado en su mejor presentación para usarlo como foto principal. "'
content = content.replace(old_task, new_task)

old_output = """  "instrucciones": ["Paso 1", "Paso 2"],"""
new_output = """  "instrucciones": ["Paso 1", "Paso 2"],\n  "best_frame_timestamp": 0.0,"""
content = content.replace(old_output, new_output)

# 3. Add OpenCV logic and the final cleanup
old_end = """        return {"media_id": media_id, "recipe": recipe}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en generateContent: {str(e)}")"""

new_end = """        
        # Extraer frame con OpenCV
        try:
            best_timestamp = float(recipe.get("best_frame_timestamp", 0.0))
            import cv2
            cap = cv2.VideoCapture(tmp_path)
            cap.set(cv2.CAP_PROP_POS_MSEC, best_timestamp * 1000)
            success, frame = cap.read()
            if success:
                import os
                os.makedirs("static/thumbnails", exist_ok=True)
                cv2.imwrite(f"static/thumbnails/{media_id}.png", frame)
            cap.release()
        except Exception as cv_err:
            print(f"Error extracting frame with cv2: {cv_err}")

        return {"media_id": media_id, "recipe": recipe}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en generateContent: {str(e)}")
    finally:
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except:
                pass"""

content = content.replace(old_end, new_end)

with open('backend/ig_recetas.py', 'w', encoding='utf-8') as f:
    f.write(content)
