# คู่มือติดตั้งและใช้งาน (GeoServer + XAMPP + Python)

ระบบนี้ทำตามแนวทางที่อาจารย์แนะนำในคลิปเสียง คือแบ่งเป็น 3 ส่วน

```
  [ หน้าเว็บ ]            [ Python Backend ]          [ GeoServer ]
  Leaflet/MapLibre   →    FastAPI + rasterio    →     เผยแพร่ WMS
  เสิร์ฟผ่าน XAMPP        คำนวณ AHP + WLC              (สไตล์ SLD)
       ↑                   เขียนไฟล์ .tif                   │
       └───────────────── โหลดแผนที่ผลลัพธ์กลับมา ────────────┘
```

**ระบบทำงานได้แม้ยังไม่ได้ติดตั้ง GeoServer** — จะใช้โหมดภาพ PNG ไปก่อน
พอเปิด GeoServer แล้วค่อยสลับเป็น WMS อัตโนมัติ ไม่ต้องแก้โค้ด

ระบบส่งผลลัพธ์ GeoTIFF ผ่าน REST upload เป็นค่าเริ่มต้น จึงใช้ได้แม้ FastAPI
กับ GeoServer อยู่คนละ container หรือคนละ Render service การใช้ `file://` แบบเดิม
ยังเปิดได้ด้วย `GEOSERVER_UPLOAD_MODE=external` เมื่อทั้งสองบริการ mount โฟลเดอร์ร่วมกัน

---

## ขั้นที่ 1 — รัน Python Backend (จำเป็นเสมอ)

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

ทดสอบว่าทำงาน: เปิดเบราว์เซอร์ไปที่ `http://127.0.0.1:8000/api/factors`
ต้องเห็น JSON รายชื่อ 6 ปัจจัย **ปล่อยหน้าต่างนี้ทิ้งไว้ตลอดเวลาที่ใช้งาน**

## ขั้นที่ 2 — เปิดหน้าเว็บผ่าน XAMPP

1. เปิด **XAMPP Control Panel** → กด **Start** ที่แถว **Apache**
   (ไม่ต้อง Start MySQL เพราะระบบนี้ไม่ใช้ฐานข้อมูล)
   - ถ้า Apache ไม่ขึ้นสีเขียว/ขึ้น error พอร์ต 80 ชนกัน: กด **Config → Apache
     (httpd.conf)** แล้วเปลี่ยน `Listen 80` เป็น `Listen 8080` จากนั้นเข้าเว็บที่
     `http://localhost:8080/...` แทน
2. คัดลอกโฟลเดอร์โปรเจกต์นี้ทั้งหมดไปวางที่ `C:\xampp\htdocs\`
3. เข้า `http://localhost/webwijai-ahp-geoserver/frontend/index.html`

> หน้าเว็บจะตรวจเองว่าเปิดจาก localhost แล้วต่อ backend ที่ `127.0.0.1:8000`
> ให้อัตโนมัติ (ดูตัวแปร `LOCAL_BACKEND` ใน `js/app.js` ถ้าต้องการเปลี่ยนพอร์ต)

---

## ขั้นที่ 3 — ติดตั้ง GeoServer (ทำเมื่อพร้อม)

### 3.1 ติดตั้ง

1. ติดตั้ง **Java JDK 11 ขึ้นไป** ก่อน — ดาวน์โหลดจาก https://adoptium.net
2. ดาวน์โหลด GeoServer จาก https://geoserver.org/download/
   เลือก **Platform Independent Binary** (หรือตัวติดตั้ง Windows ก็ได้)
3. แตกไฟล์ แล้วรัน `bin\startup.bat` (Windows) — ปล่อยหน้าต่างนี้เปิดทิ้งไว้
4. เข้า `http://localhost:8080/geoserver` → ล็อกอินด้วย `admin` / `geoserver`

> ถ้า XAMPP ใช้พอร์ต 8080 อยู่แล้ว ให้เปลี่ยนพอร์ตของฝั่งใดฝั่งหนึ่ง
> เพื่อไม่ให้ชนกัน

### 3.2 เปิดใช้งานฝั่ง Python

**ไม่ต้องสร้าง workspace / store / style เองใน GeoServer**
ระบบจะสร้างให้อัตโนมัติผ่าน REST API ตอนกดคำนวณครั้งแรก

ปิด uvicorn เดิม แล้วรันใหม่พร้อมตั้งค่า:

**Windows (PowerShell)**
```powershell
cd backend
$env:GEOSERVER_ENABLED="true"
$env:GEOSERVER_URL="http://localhost:8080/geoserver"
$env:GEOSERVER_USER="admin"
$env:GEOSERVER_PASS="geoserver"
python -m uvicorn main:app --reload --port 8000
```

**Windows (Command Prompt)**
```cmd
cd backend
set GEOSERVER_ENABLED=true
set GEOSERVER_URL=http://localhost:8080/geoserver
set GEOSERVER_USER=admin
set GEOSERVER_PASS=geoserver
python -m uvicorn main:app --reload --port 8000
```

**macOS / Linux**
```bash
cd backend
export GEOSERVER_ENABLED=true
python -m uvicorn main:app --reload --port 8000
```

ดูตัวเลือกทั้งหมดได้ที่ `backend/.env.example`

### 3.3 ตรวจสอบว่าเชื่อมต่อได้

เปิด `http://127.0.0.1:8000/api/geoserver-status`

| ข้อความที่เห็น | แปลว่า |
|---|---|
| `เชื่อมต่อ GeoServer สำเร็จ` | พร้อมใช้งาน |
| `ปิดการใช้งาน GeoServer อยู่` | ยังไม่ได้ตั้ง `GEOSERVER_ENABLED=true` |
| `เชื่อมต่อ ... ไม่ได้` | ยังไม่ได้เปิด GeoServer หรือพอร์ตไม่ตรง |
| `user/password ไม่ถูกต้อง` | รหัสผ่านถูกเปลี่ยนไปแล้ว |

---

## ระบบทำอะไรให้บ้างตอนกด "คำนวณแผนที่"

1. คำนวณ WLC จากน้ำหนัก AHP (`S = Σ wi·xi` ตามหัวข้อ 2.4 ของเล่ม)
2. จำแนกเป็น 4 ระดับตามมาตรฐาน FAO แล้วเขียนเป็นไฟล์
   `backend/output/suitability_result.tif` (EPSG:4326, ค่า 1=N, 2=S3, 3=S2, 4=S1,
   0=นอกเขตจังหวัด)
3. สั่ง GeoServer สร้าง workspace `sugarcane` + สไตล์ SLD + publish เลเยอร์
4. ล้าง cache ของ GeoWebCache ไม่ให้ค้างภาพเก่า
5. หน้าเว็บโหลดเลเยอร์ WMS มาแสดง

**ถ้าขั้นที่ 3 ไม่สำเร็จ ระบบจะไม่ error** — จะแสดงภาพ PNG แทน พร้อมข้อความ
บอกสาเหตุมุมขวาบนของหน้าเว็บ

### เปิดดูเลเยอร์ใน QGIS / ArcMap ด้วยก็ได้

นี่คือข้อดีของการใช้ GeoServer — เปิดจากโปรแกรม GIS อื่นได้ด้วย URL เดียว:

```
http://localhost:8080/geoserver/sugarcane/wms
```
(QGIS: Layer → Add Layer → Add WMS/WMTS Layer → New → วาง URL ด้านบน)

---

## ปัญหาที่พบบ่อย

| อาการ | วิธีแก้ |
|---|---|
| หน้าเว็บขึ้น "ไม่สามารถเชื่อมต่อกับ Python Backend ได้" | หน้าต่าง uvicorn ถูกปิดไป ให้เปิดใหม่ตามขั้นที่ 1 |
| แผนที่ไม่อัปเดตหลังกดคำนวณ | ล้าง cache: GeoServer → Tile Caching → Tile Layers → Empty |
| `publish ไม่สำเร็จ (HTTP 500)` | ตรวจ `GEOSERVER_URL`, user/password และสถานะ REST ของ GeoServer; ถ้าใช้ `GEOSERVER_UPLOAD_MODE=external` ต้องให้ GeoServer อ่านพาธไฟล์ `.tif` ได้ด้วย |
| เลเยอร์ขึ้นเป็นสีเทาทึบ | สไตล์ยังไม่ถูกผูก — เข้า GeoServer → Layers → เลือกเลเยอร์ → tab Publishing → Default Style = `suitability_fao` |

## ทดสอบการอัปโหลดไฟล์จริง

สร้างไฟล์ตัวอย่างที่เป็น GeoTIFF และ Shapefile ZIP ได้ด้วยคำสั่งนี้:

```powershell
python backend/tools/create_upload_fixtures.py
```

จะได้ `upload-fixtures/khonkaen-demo-layer.tif` และ
`upload-fixtures/khonkaen-demo-layer-shapefile.zip` ซึ่งเป็นไฟล์ EPSG:4326
ขนาดเล็กสำหรับอัปโหลดผ่านปุ่มของแต่ละปัจจัยในหน้าเว็บ ไฟล์ Shapefile จะใช้
`geopandas/fiona` เมื่อมีไลบรารีครบ และจะ fallback เป็น `pyshp + shapely`
เมื่อสภาพแวดล้อมไม่มี GDAL/Fiona
