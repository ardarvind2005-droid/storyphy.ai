# app.py
import os
import io
import json
import base64
import uuid
from flask import Flask, request, render_template, send_file, redirect, url_for, flash
import requests
from weasyprint import HTML

# ---- Configuration ----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
STABILITY_API_KEY = os.getenv("STABILITY_API_KEY", "")
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "openai")

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "devsecret")

def generate_story_with_openai(name, age, theme, tone, pages=6):
    if not OPENAI_API_KEY:
        sample = {
            "title": f"{name} and the {theme.title()} Adventure",
            "synopsis": f"A short {tone} tale about {name}.",
            "pages": []
        }
        for i in range(1, pages + 1):
            sample["pages"].append({
                "page": i,
                "page_text": f"Page {i}: {name} does something fun in the {theme}.",
                "image_description": f"{name} (age {age}) in a {theme} scene, playful composition."
            })
        return sample

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    system = (
        "You are a children's story writer. Output valid JSON with fields: title, synopsis, pages. "
        "pages should be a list of objects with page (int), page_text (1-2 short sentences), image_description (short)."
    )
    user_prompt = (
        f"Write a children's story for a {age}-year-old named {name}. Theme: {theme}. Tone: {tone}. "
        f"Make {pages} pages. Return only JSON (no extra text)."
    )
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 800,
        "temperature": 0.8
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    text = data["choices"][0]["message"]["content"]
    try:
        story_json = json.loads(text)
        return story_json
    except Exception as e:
        raise RuntimeError(f"LLM returned unparsable JSON. Raw text:\n{text}") from e

def generate_image_openai(prompt, size="1024x1024", seed=None):
    if not OPENAI_API_KEY:
        return None
    url = "https://api.openai.com/v1/images/generations"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {"prompt": prompt, "n": 1, "size": size}
    if seed is not None:
        payload["seed"] = seed
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    j = r.json()
    b64 = j["data"][0]["b64_json"]
    img_bytes = base64.b64decode(b64)
    return img_bytes

def generate_image_stability(prompt, width=1024, height=1024, seed=None):
    if not STABILITY_API_KEY:
        return None
    url = "https://api.stability.ai/v1/generation/stable-diffusion-v1-5/text-to-image"
    headers = {"Authorization": f"Bearer {STABILITY_API_KEY}"}
    payload = {
        "text_prompts": [{"text": prompt}],
        "width": width,
        "height": height,
        "samples": 1,
    }
    if seed is not None:
        payload["seed"] = seed
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    j = r.json()
    b64 = j["artifacts"][0]["base64"]
    img_bytes = base64.b64decode(b64)
    return img_bytes

def generate_image(prompt, provider_hint=None, seed=None):
    provider = provider_hint or IMAGE_PROVIDER
    uid = uuid.uuid4().hex[:12]
    out_path = os.path.join(OUTPUT_DIR, f"img_{uid}.png")

    if provider == "openai":
        img_bytes = generate_image_openai(prompt, size="1024x1024", seed=seed)
    elif provider == "stability":
        img_bytes = generate_image_stability(prompt, width=1024, height=1024, seed=seed)
    else:
        img_bytes = None

    if img_bytes:
        with open(out_path, "wb") as f:
            f.write(img_bytes)
        return out_path
    return None

@app.route("/", methods=["GET"])
def index():
    return render_template("form.html")

@app.route("/create", methods=["POST"])
def create():
    data = request.form
    child_name = data.get("name", "Child")
    age = data.get("age", "5")
    theme = data.get("theme", "jungle")
    tone = data.get("tone", "playful")
    pages = int(data.get("pages", 6))

    try:
        story = generate_story_with_openai(child_name, age, theme, tone, pages=pages)
    except Exception as e:
        flash(f"Error generating story: {e}")
        return redirect(url_for("index"))

    page_images = []
    char_token = f"CHAR_{child_name.upper()}_V1"
    child_descriptor = f"{child_name}, age {age}, child character, friendly face, consistent across pages."

    for p in story.get("pages", []):
        image_prompt = (
            f"{char_token}: {child_descriptor}. {p.get('image_description','')}. "
            "Cartoon style, kid-friendly, bright colors, soft rounded shapes. Full scene for a children's book. "
            "High detail for print, 300 DPI."
        )
        try:
            img_path = generate_image(image_prompt, seed=hash((child_name, p.get('page', 0))) % (2**32))
        except Exception as e:
            img_path = None

        page_images.append(img_path)

    rendered = render_template("story.html", story=story, images=page_images, child_name=child_name)

    html_file = os.path.join(OUTPUT_DIR, f"story_{uuid.uuid4().hex[:8]}.html")
    with open(html_file, "w", encoding="utf-8") as fh:
        fh.write(rendered)

    pdf_bytes = HTML(string=rendered, base_url=os.path.abspath(".")).write_pdf()

    pdf_path = os.path.join(OUTPUT_DIR, f"{child_name}_storybook_{uuid.uuid4().hex[:8]}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)

    return send_file(io.BytesIO(pdf_bytes),
                     as_attachment=True,
                     download_name=f"{child_name}_storybook.pdf",
                     mimetype="application/pdf")

if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", 5000)))
