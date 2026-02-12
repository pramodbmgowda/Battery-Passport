import os
import qrcode
import sqlite3
from uuid import uuid4
from datetime import datetime
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing

app = FastAPI()

# --- CONFIGURATION ---
DOMAIN = "http://10.69.199.1:8000"  # REPLACE with your Cloud URL later
LABEL_SIZE = (50 * mm, 50 * mm)     # Standard 50x50mm Industrial Label

# Setup Folders
os.makedirs("static/qr_codes", exist_ok=True)
os.makedirs("static/labels", exist_ok=True) # New folder for PDFs
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- DATABASE (Enhanced Schema) ---
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    # Added Global Standard Fields: capacity, voltage, cycle_life
    c.execute('''CREATE TABLE IF NOT EXISTS batteries
                 (id TEXT PRIMARY KEY, 
                  producer_name TEXT, 
                  epr_number TEXT, 
                  battery_type TEXT, 
                  brand_name TEXT,
                  chemistry TEXT,
                  capacity_ah REAL,
                  voltage_v REAL,
                  weight_kg REAL,
                  mfg_date TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- HELPER: Industrial PDF Generator ---
def generate_thermal_label(batch_id, epr_no, brand, url):
    filename = f"static/labels/{batch_id}.pdf"
    c = canvas.Canvas(filename, pagesize=LABEL_SIZE)
    
    # 1. Draw QR Code
    qr_code = qr.QrCodeWidget(url)
    qr_code.barWidth = 33 * mm
    qr_code.barHeight = 33 * mm
    qr_code.qrVersion = 1
    d = Drawing(33 * mm, 33 * mm)
    d.add(qr_code)
    # Position QR code (Centered, Top)
    from reportlab.graphics import renderPDF
    renderPDF.draw(d, c, 8 * mm, 15 * mm)

    # 2. Draw Text (Thermal Printer Optimized Font)
    c.setFont("Helvetica-Bold", 6)
    c.drawCentredString(25 * mm, 12 * mm, f"BRAND: {brand.upper()}")
    c.setFont("Helvetica", 5)
    c.drawCentredString(25 * mm, 9 * mm, f"EPR: {epr_no}")
    c.drawCentredString(25 * mm, 6 * mm, f"ID: {batch_id[:8]}")
    
    # 3. Draw Mandatory "Wheelie Bin" (Simplified as X-Box for Demo)
    # In production, use an actual image: c.drawImage("bin.png", ...)
    c.rect(42*mm, 2*mm, 6*mm, 6*mm)
    c.line(42*mm, 2*mm, 48*mm, 8*mm)
    c.line(42*mm, 8*mm, 48*mm, 2*mm)
    c.setFont("Helvetica", 4)
    c.drawString(42*mm, 1*mm, "Do Not Bin")

    c.save()
    return filename

# --- ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def read_form(request: Request):
    return templates.TemplateResponse("input_form.html", {"request": request})

@app.post("/generate")
async def generate_passport(
    request: Request,
    producer_name: str = Form(...),
    epr_number: str = Form(...),
    brand_name: str = Form(...),
    battery_type: str = Form(...),
    chemistry: str = Form(...),
    capacity: float = Form(...),  # New Field
    voltage: float = Form(...),   # New Field
    weight: float = Form(...)
):
    batch_id = str(uuid4())
    mfg_date = datetime.now().strftime("%Y-%m-%d")

    # 1. Save Data
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("INSERT INTO batteries VALUES (?,?,?,?,?,?,?,?,?,?)",
              (batch_id, producer_name, epr_number, battery_type, brand_name, chemistry, capacity, voltage, weight, mfg_date))
    conn.commit()
    conn.close()

    # 2. Generate Assets
    passport_url = f"{DOMAIN}/verify/{batch_id}"
    pdf_path = generate_thermal_label(batch_id, epr_number, brand_name, passport_url)
    
    # Generate PNG for Web Preview (using old method for screen)
    qr_img = qrcode.make(passport_url)
    qr_png_path = f"static/qr_codes/{batch_id}.png"
    qr_img.save(qr_png_path)

    return templates.TemplateResponse("passport.html", {
        "request": request,
        "data": {
            "id": batch_id,
            "epr": epr_number,
            "name": brand_name,
            "pdf_link": f"/{pdf_path}",
            "qr_png": f"/{qr_png_path}",
            "is_preview": True
        }
    })

@app.get("/verify/{batch_id}", response_class=HTMLResponse)
async def verify_battery(request: Request, batch_id: str):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM batteries WHERE id=?", (batch_id,))
    row = c.fetchone()
    conn.close()

    if row:
        data = {
            "id": row[0],
            "producer": row[1],
            "epr": row[2],
            "type": row[3],
            "brand": row[4],
            "chemistry": row[5],
            "capacity": row[6],
            "voltage": row[7],
            "weight": row[8],
            "date": row[9],
            "is_preview": False
        }
        return templates.TemplateResponse("passport.html", {"request": request, "data": data})
    else:
        return HTMLResponse(content="<h1>⚠️ Warning: Counterfeit Battery Detected</h1>", status_code=404)