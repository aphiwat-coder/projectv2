# Sugarcane AHP WebGIS

ระบบประเมินความเหมาะสมพื้นที่ปลูกอ้อยจังหวัดขอนแก่นด้วย AHP/WLC

## โครงสร้าง

```text
frontend/              static HTML/CSS/JavaScript
backend/               FastAPI และการประมวลผลภูมิสารสนเทศ
backend/data/          ข้อมูลขอบเขตจังหวัดและข้อมูลโรงงาน
deploy/                Docker Compose และ Nginx สำหรับ full stack
render.yaml            Render Blueprint สำหรับ frontend + backend + GeoServer WMS
```

## Deploy บน Render พร้อม GeoServer WMS

สร้าง Blueprint จาก `render.yaml` ใน repository นี้ ระบบจะแยกเป็นสาม service:

- `projectv2-api`: FastAPI จากโฟลเดอร์ `backend`
- `projectv2-frontend`: static site จากโฟลเดอร์ `frontend`
- `projectv2-geoserver`: GeoServer 2.28.2 จาก Docker image

หลังได้ URL ของ API แล้ว ให้ใส่ URL นั้นใน `frontend/js/config.js`:

```js
remoteBackend: "https://ชื่อ-apiของคุณ.onrender.com"
```

แล้ว commit/push อีกครั้งเพื่อให้ frontend เรียก API ได้

ถ้าอัปโหลด GeoTIFF แล้วขึ้นว่าไม่พบ `rasterio` ให้กด **Manual Deploy → Clear
build cache & deploy** ของ service API หลัง sync Blueprint แล้วตรวจว่า service
ใช้ `Root Directory = backend` และ `Build Command` เป็นการติดตั้ง
`requirements.txt` ในโฟลเดอร์นั้น การอัปโหลดไฟล์ WGS84 (EPSG:4326) ยังมีตัวอ่าน
สำรองด้วย `tifffile`/`imagecodecs` เพื่อรองรับ GeoTIFF ที่บีบอัดแบบ PackBits และ
LZW; ไฟล์ที่เป็น CRS อื่นต้องใช้ rasterio เพื่อ reproject

Blueprint ตั้ง `GEOSERVER_ENABLED=true` และใช้ `GEOSERVER_UPLOAD_MODE=upload` โดยส่ง
GeoTIFF ผ่าน REST API จึงไม่ต้องใช้ shared disk ระหว่าง Render services เมื่อกด
คำนวณสำเร็จ หน้าเว็บจะแสดงผลผ่าน WMS; ถ้า GeoServer กำลังตื่นหรือเชื่อมต่อไม่ได้
ระบบยังคงใช้ภาพ PNG สำรองให้โดยอัตโนมัติ

ค่าเริ่มต้นของ image service ใช้ `admin/geoserver` เพื่อให้เริ่มใช้งานได้ทันที
ควรเปลี่ยน `GEOSERVER_PASS` และ `GEOSERVER_ADMIN_PASSWORD` ใน Render Dashboard
ก่อนเปิดใช้งานจริง

ตรวจสอบหลัง deploy:

```text
https://ชื่อ-apiของคุณ.onrender.com/api/geoserver-status
https://projectv2-geoserver.onrender.com/geoserver/web/
```

ถ้า Blueprint เดิมมีแค่สอง service ให้กด sync Blueprint อีกครั้งเพื่อสร้าง
`projectv2-geoserver` และอัปเดต environment variables ของ API

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
