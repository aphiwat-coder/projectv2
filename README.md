# Sugarcane AHP WebGIS

ระบบประเมินความเหมาะสมพื้นที่ปลูกอ้อยจังหวัดขอนแก่นด้วย AHP/WLC

## โครงสร้าง

```text
frontend/              static HTML/CSS/JavaScript
backend/               FastAPI และการประมวลผลภูมิสารสนเทศ
backend/data/          ข้อมูลขอบเขตจังหวัดและข้อมูลโรงงาน
deploy/                Docker Compose และ Nginx สำหรับ full stack
render.yaml            Render Blueprint สำหรับ frontend + backend แบบไม่ใช้ GeoServer
```

## Deploy แบบง่ายบน Render

สร้าง Blueprint จาก `render.yaml` ใน repository นี้ ระบบจะแยกเป็นสอง service:

- `projectv2-api`: FastAPI จากโฟลเดอร์ `backend`
- `projectv2-frontend`: static site จากโฟลเดอร์ `frontend`

หลังได้ URL ของ API แล้ว ให้ใส่ URL นั้นใน `frontend/js/config.js`:

```js
remoteBackend: "https://ชื่อ-apiของคุณ.onrender.com"
```

แล้ว commit/push อีกครั้งเพื่อให้ frontend เรียก API ได้

โหมด Render นี้ปิด GeoServer และใช้ภาพ PNG เป็น fallback ซึ่งเหมาะสำหรับ demo

## Deploy แบบ Full Stack ด้วย Docker

ต้องมี Docker และ Docker Compose:

```bash
cd deploy
cp .env.example .env
docker compose up -d --build
```

บน PowerShell ใช้ `Copy-Item .env.example .env` แทน `cp` ได้

ถ้า deploy บนโดเมนจริง ให้แก้ `GEOSERVER_PUBLIC_URL` ใน `deploy/.env` เป็น URL ภายนอก เช่น `https://example.com/geoserver`

เปิดใช้งาน:

- เว็บ: `http://localhost/`
- FastAPI: `http://localhost:8000/docs`
- GeoServer: `http://localhost:8080/geoserver`

Compose จะ mount volume เดียวกันให้ FastAPI และ GeoServer เพื่อให้ GeoServer อ่านไฟล์ผลลัพธ์ GeoTIFF ได้

ก่อนเปิดใช้งานจริงควรเปลี่ยน `GEOSERVER_PASS`, เปิด HTTPS และจำกัด CORS

## รัน Backend แบบ local

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

จากนั้นเปิด `frontend/index.html` ผ่าน static server และตรวจ `frontend/js/config.js`

รายละเอียดการใช้งาน GeoServer เพิ่มเติมอยู่ใน [README_GEOSERVER.md](README_GEOSERVER.md)
