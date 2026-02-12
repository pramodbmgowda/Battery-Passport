import os
import qrcode
import sqlite3
from uuid import uuid4
from datetime import datetime
from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing

app = FastAPI()

# --- CONFIGURATION: UPDATE IP EVERY TIME YOU CHANGE WIFI ---
# Run 'ipconfig getifaddr en0' in terminal
DOMAIN = "https://battery-passport-s1ty.onrender.com" 
LABEL_SIZE = (50 * mm, 50 * mm)

os.makedirs("static/qr_codes", exist_ok=True)
os.makedirs("static/labels", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('DROP TABLE IF EXISTS batteries')
    c.execute('''CREATE TABLE batteries
                 (id TEXT PRIMARY KEY, 
                  producer_name TEXT, 
                  epr_number TEXT, 
                  battery_type TEXT, 
                  brand_name TEXT,
                  chemistry TEXT,
                  capacity_ah REAL,
                  voltage_v REAL,
                  weight_kg REAL,
                  batch_size INTEGER,
                  mfg_date TEXT)''')
    conn.commit()
    conn.close()

init_db()

def draw_label(c, unit_id, epr_no, brand, url):
    qr_code = qr.QrCodeWidget(url)
    qr_code.barWidth = 33 * mm
    qr_code.barHeight = 33 * mm
    d = Drawing(33 * mm, 33 * mm)
    d.add(qr_code)
    from reportlab.graphics import renderPDF
    renderPDF.draw(d, c, 8 * mm, 15 * mm)
    c.setFont("Helvetica-Bold", 6)
    c.drawCentredString(25 * mm, 12 * mm, f"BRAND: {brand.upper()}")
    c.setFont("Helvetica", 5)
    c.drawCentredString(25 * mm, 9 * mm, f"EPR: {epr_no}")
    c.drawCentredString(25 * mm, 6 * mm, f"UID: {unit_id}")
    # Compliance Symbols
    c.rect(42*mm, 2*mm, 6*mm, 6*mm)
    c.line(42*mm, 2*mm, 48*mm, 8*mm)
    c.line(42*mm, 8*mm, 48*mm, 2*mm)

@app.get("/", response_class=HTMLResponse)
async def read_form(request: Request):
    return templates.TemplateResponse("input_form.html", {"request": request})

@app.post("/generate")
async def generate_passport(
    request: Request,
    producer_name: str = Form(...),
    epr_number: str = Form(...),
    brand_name: str = Form("BATCH-PRODUCT"),
    battery_type: str = Form(...),
    chemistry: str = Form(...),
    capacity: float = Form(...),
    voltage: float = Form(...),
    weight: float = Form(...),
    batch_size: int = Form(1),
    is_unique: bool = Form(False)
):
    master_batch_id = str(uuid4())[:12]
    mfg_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    pdf_path = f"static/labels/{master_batch_id}.pdf"
    c = canvas.Canvas(pdf_path, pagesize=LABEL_SIZE)

    conn = sqlite3.connect('database.db')
    db = conn.cursor()

    if is_unique:
        for i in range(batch_size):
            u_id = f"{master_batch_id}-U{i+1}"
            u_url = f"{DOMAIN}/verify/{u_id}"
            db.execute("INSERT INTO batteries VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (u_id, producer_name, epr_number, battery_type, brand_name, chemistry, capacity, voltage, weight, 1, mfg_date))
            draw_label(c, u_id, epr_number, brand_name, u_url)
            c.showPage()
    else:
        u_url = f"{DOMAIN}/verify/{master_batch_id}"
        db.execute("INSERT INTO batteries VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (master_batch_id, producer_name, epr_number, battery_type, brand_name, chemistry, capacity, voltage, weight, batch_size, mfg_date))
        draw_label(c, master_batch_id, epr_number, brand_name, u_url)
        c.showPage()

    c.save()
    conn.commit()
    conn.close()

    preview_id = f"{master_batch_id}-U1" if is_unique else master_batch_id
    qr_preview = qrcode.make(f"{DOMAIN}/verify/{preview_id}")
    qr_preview.save(f"static/qr_codes/{master_batch_id}.png")

    return templates.TemplateResponse("passport.html", {
        "request": request,
        "data": {"id": master_batch_id, "epr": epr_number, "name": brand_name, "size": batch_size,
                "pdf_link": f"/{pdf_path}", "qr_png": f"/static/qr_codes/{master_batch_id}.png",
                "is_preview": True, "mode": "Unique" if is_unique else "Batch"}
    })

@app.get("/verify/{battery_id}", response_class=HTMLResponse)
async def verify_battery(request: Request, battery_id: str):
    conn = sqlite3.connect('database.db')
    db = conn.cursor()
    db.execute("SELECT * FROM batteries WHERE id = ?", (battery_id,))
    row = db.fetchone()
    conn.close()

    if row:
        data = {"id": row[0], "producer": row[1], "epr": row[2], "type": row[3],
                "brand": row[4], "chemistry": row[5], "capacity": row[6],
                "voltage": row[7], "weight": row[8], "size": row[9], "date": row[10], "is_preview": False}
        return templates.TemplateResponse("passport.html", {"request": request, "data": data})
    else:
        return HTMLResponse(content=f"<h1>ID {battery_id} Not Found</h1>", status_code=404)