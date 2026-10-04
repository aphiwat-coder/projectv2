import base64
import io
import json
import pathlib
import zlib
import tempfile
import zipfile
import os

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from PIL import Image

import geoserver_publish as gs
from pydantic import BaseModel, field_validator

app = FastAPI(title="AHP WebGIS Sugarcane - Khon Kaen")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class AHPRequest(BaseModel):
    factors: list[str]
    matrix: list[list[float]]

    @field_validator("matrix")
    @classmethod
    def check_square(cls, m, info):
        n = len(m)
        if any(len(row) != n for row in m):
            raise ValueError("matrix ต้องเป็นเมทริกซ์จัตุรัส (n x n)")
        return m

RI_TABLE = {
    1: 0.00, 2: 0.00, 3: 0.58, 4: 0.90, 5: 1.12,
    6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49,
}

def solve_ahp_weights(matrix: list[list[float]]) -> dict:
    A = np.array(matrix, dtype=float)
    n = A.shape[0]

    eigenvalues, eigenvectors = np.linalg.eig(A)
    max_index = int(np.argmax(np.real(eigenvalues)))
    max_lambda = float(np.real(eigenvalues[max_index]))
    principal_vector = np.real(eigenvectors[:, max_index])

    if np.sum(principal_vector) < 0:
        principal_vector = -principal_vector

    weights = principal_vector / np.sum(principal_vector)

    ci = (max_lambda - n) / (n - 1) if n > 1 else 0.0
    ri = RI_TABLE.get(n, 1.49)
    cr = ci / ri if ri > 0 else 0.0

    return {
        "weights": weights,
        "lambda_max": max_lambda,
        "ci": ci,
        "cr": cr,
        "is_consistent": bool(cr < 0.10),
    }

@app.post("/api/ahp-calculate")
def calculate_ahp(data: AHPRequest):
    n = len(data.factors)
    if len(data.matrix) != n:
        raise HTTPException(400, "จำนวนแถวของ matrix ไม่ตรงกับจำนวน factors")

    solved = solve_ahp_weights(data.matrix)
    weight_dict = {
        data.factors[i]: round(float(solved["weights"][i]), 4) for i in range(n)
    }

    result = {
        "status": "success",
        "weights": weight_dict,
        "lambda_max": round(solved["lambda_max"], 4),
        "ci": round(solved["ci"], 4),
        "cr": round(solved["cr"], 4),
        "is_consistent": solved["is_consistent"],
    }
    return result

# กรอบพิกัดโดยประมาณของจังหวัดขอนแก่น (WGS84 lon/lat)
# แก้ไข: ของเดิม (west=102.35, east=103.30, south=15.95, north=16.85) แคบเกินไป
# ตัดพื้นที่จริงทางตะวันตก/เหนือ/ใต้ของจังหวัดออกไปหลายอำเภอ (เช่น ภูเวียง,
# หนองนาคำ, เขาสวนกวาง) ปรับให้ครอบคลุมขอบเขตจริงทั้งหมดของจังหวัด (จากขอบเขต
# การปกครองจริงใน backend/data/khonkaen_boundary.geojson) พร้อม buffer เล็กน้อย
KHONKAEN_BOUNDS = {"west": 101.70, "east": 103.25, "south": 15.55, "north": 17.15}
# ปรับความละเอียดให้คมชัดขึ้น
GRID_WIDTH = 480
GRID_HEIGHT = 400

raw_layers: dict[str, np.ndarray] = {}
uploaded_layers: dict[str, np.ndarray] = {}
classification_tables: dict[str, list[dict]] = {}

# ตัวแปรสำหรับเก็บผลลัพธ์ความเหมาะสมล่าสุดเพื่อนำไปส่งออกไฟล์
last_suitability_result = {"array": None}

# ==================================================================
# ขอบเขตจังหวัดขอนแก่นจริง (สำหรับตัดภาพให้เป็นรูปทรงจังหวัด ไม่ใช่สี่เหลี่ยม)
# ที่มา: apisit/thailand.json (ขอบเขตการปกครองระดับจังหวัด, MIT License)
# ==================================================================
_BOUNDARY_PATH = os.path.join(os.path.dirname(__file__), "data", "khonkaen_boundary.geojson")
_province_mask_cache = None  # cache ไว้ครั้งแรกที่คำนวณ (ไม่ต้องคำนวณซ้ำทุก request)


def get_province_mask() -> np.ndarray:
    """
    คืน boolean array ขนาด (GRID_HEIGHT, GRID_WIDTH) — True = จุดกึ่งกลาง cell
    นั้นอยู่ *ภายใน* ขอบเขตจังหวัดขอนแก่นจริง (ไม่ใช่แค่ในกรอบสี่เหลี่ยม)
    ใช้ตัด alpha=0 (โปร่งใส) ให้กับ cell ที่อยู่นอกจังหวัด ตอนแปลงเป็นภาพ PNG
    """
    global _province_mask_cache
    if _province_mask_cache is not None:
        return _province_mask_cache

    try:
        from shapely.geometry import shape
        import shapely

        with open(_BOUNDARY_PATH, encoding="utf-8") as f:
            boundary = json.load(f)
        polygon = shape(boundary["geometry"])
        LON, LAT = _grid_lonlat()
        # shapely.vectorized.contains ถูกถอดออกใน Shapely 2.x แล้ว ใช้
        # shapely.contains() แบบเวกเตอร์ของ Shapely 2.x แทน (ต้องสร้างจุด
        # ด้วย shapely.points() ก่อน แล้วเช็คทีละจุดแบบขนาน)
        points = shapely.points(LON.ravel(), LAT.ravel())
        _province_mask_cache = shapely.contains(polygon, points).reshape(LON.shape)
    except Exception as e:
        # ถ้าโหลดขอบเขตไม่สำเร็จ (ไฟล์หาย/shapely ไม่มี) ให้ fallback เป็น
        # "ทุก cell อยู่ในขอบเขต" (พฤติกรรมเดิมก่อนแก้ไข) แทนที่จะให้ระบบล่ม
        print(f"⚠️  โหลดขอบเขตจังหวัดไม่สำเร็จ (จะแสดงเป็นสี่เหลี่ยมแทนรูปทรงจริง): {e}")
        _province_mask_cache = np.ones((GRID_HEIGHT, GRID_WIDTH), dtype=bool)

    return _province_mask_cache


# ==================================================================
# โหลดข้อมูลโรงงานน้ำตาลล่วงหน้าอัตโนมัติตอนเปิดระบบ (Optional)
# ==================================================================
FACTORIES_FILE = pathlib.Path(__file__).parent / "data" / "factories.json"
# ปัจจัยลำดับที่ 6 ของเล่มรายงานคือ "การคมนาคม" (ตารางที่ 7: ระยะห่างจากถนน)
# ตอนนี้ยังไม่มีชั้นข้อมูลถนนจริง จึงใช้ "ระยะห่างจากโรงงานน้ำตาล" เป็นตัวแทน
# ไปก่อน (มีพิกัดจริง 2 โรงงานใน data/factories.json) เมื่อได้ชั้นข้อมูลถนนจาก
# DIVA-GIS แล้ว ให้อัปโหลดทับปัจจัย "transport" ผ่านหน้าเว็บได้ทันที
FACTORY_LAYER_NAME = "transport"


def load_default_factory_layer():
    """
    โหลดพิกัดโรงงานน้ำตาลจากไฟล์ backend/data/factories.json (ถ้ามี) แล้วคำนวณ
    ชั้นข้อมูล "ระยะห่างจากโรงงานน้ำตาลที่ใกล้ที่สุด" (กิโลเมตร) ไว้ล่วงหน้า
    ให้พร้อมใช้งานทันทีตั้งแต่เปิดระบบ โดยไม่ต้องอัปโหลดไฟล์เองผ่านหน้าเว็บ
    เพื่อดูเลเยอร์นี้บนแผนที่ ให้เพิ่มปัจจัยชื่อ "DistanceToFactory" ในหน้าเว็บ
    """
    if not FACTORIES_FILE.exists():
        print(f"ℹ️  ไม่พบไฟล์ {FACTORIES_FILE} — ข้ามการโหลดข้อมูลโรงงานน้ำตาล (ไม่ใช่ข้อผิดพลาด)")
        return
    try:
        from shapely.geometry import Point
        from shapely.ops import unary_union
        import shapely
    except ImportError:
        print("⚠️  ต้องติดตั้งไลบรารี shapely ก่อนจึงจะโหลดข้อมูลโรงงานได้")
        return
    try:
        with open(FACTORIES_FILE, encoding="utf-8") as f:
            factories = json.load(f)
        if not factories:
            print("⚠️  ไฟล์ factories.json ว่างเปล่า ข้ามการโหลด")
            return
        geoms = [Point(item["longitude"], item["latitude"]) for item in factories]
        merged = unary_union(geoms)
        LON, LAT = _grid_lonlat()
        points = shapely.points(LON.ravel(), LAT.ravel())
        distances_deg = shapely.distance(points, merged).reshape(LON.shape)
        distances_km = distances_deg * 111.32
        raw_layers[FACTORY_LAYER_NAME] = distances_km
        # แก้บั๊ก: เดิมใช้ _normalize() ตรงๆ ทำให้ "ยิ่งไกลโรงงาน ยิ่งได้คะแนนสูง"
        # ซึ่งกลับด้านกับความจริง (เล่มรายงาน บทที่ 1 ระบุว่าไกลเกิน 50 กม. ค่า CCS
        # ตกและต้นทุนขนส่งสูง) จึงต้องกลับค่าให้ "ยิ่งใกล้ ยิ่งคะแนนสูง"
        uploaded_layers[FACTORY_LAYER_NAME] = 1.0 - _normalize_masked(distances_km)
        names = ", ".join(item.get("factory_name", "?") for item in factories)
        print(f"✅ โหลดข้อมูลโรงงานน้ำตาล {len(factories)} แห่งสำเร็จ: {names}")
    except Exception as e:
        print(f"⚠️  ไม่สามารถโหลดพิกัดโรงงานได้: {e}")


@app.on_event("startup")
def startup_event():
    pass  # <--- เติมคำว่า pass เข้าไปบรรทัดนี้ครับ
    # load_default_factory_layer()


def _normalize(a: np.ndarray) -> np.ndarray:
    a = a.astype(float)
    rng = a.max() - a.min()
    if rng < 1e-9:
        return np.zeros_like(a)
    return (a - a.min()) / rng

def _normalize_masked(a: np.ndarray) -> np.ndarray:
    """เหมือน _normalize() แต่คิด min/max จากเฉพาะ cell ที่อยู่ในขอบเขตจังหวัดจริง
    (get_province_mask()) ไม่ปนกับ cell นอกจังหวัดซึ่งเป็นแค่ "พื้นที่ว่าง" ในกรอบ
    สี่เหลี่ยมที่ใช้คำนวณ และไม่มีความหมายทางภูมิศาสตร์
    เหตุผล: กริดทั้งหมดมีแค่ ~36% ที่อยู่ในจังหวัดจริง ถ้า normalize จากทั้งกรอบ
    ค่า 0-1 ที่ได้จะถูกดึงโดยข้อมูลนอกจังหวัด ทำให้สีและสถิติของพื้นที่จริงเพี้ยน"""
    mask = get_province_mask()
    a = a.astype(float)
    inside = a[mask]
    if inside.size == 0:
        return _normalize(a)
    lo, hi = inside.min(), inside.max()
    if hi - lo < 1e-9:
        return np.zeros_like(a)
    return np.clip((a - lo) / (hi - lo), 0, 1)

def _grid_lonlat():
    lon = np.linspace(KHONKAEN_BOUNDS["west"], KHONKAEN_BOUNDS["east"], GRID_WIDTH)
    lat = np.linspace(KHONKAEN_BOUNDS["north"], KHONKAEN_BOUNDS["south"], GRID_HEIGHT)
    return np.meshgrid(lon, lat)

# ==================================================================
# 6 ปัจจัยหลักตามเล่มรายงาน (ตารางที่ 10-11) — ชื่อ key ต้องตรงกับฝั่งเว็บ
# ==================================================================
FACTOR_ORDER = ["soil", "water", "rainfall", "drought", "flood", "transport"]

FACTOR_LABELS_TH = {
    "soil": "ประเภทดิน",
    "water": "แหล่งน้ำ",
    "rainfall": "ปริมาณน้ำฝน",
    "drought": "พื้นที่เสี่ยงภัยแล้ง",
    "flood": "พื้นที่น้ำท่วม",
    "transport": "การคมนาคม",
}

# น้ำหนักอ้างอิงจากผลการคำนวณ AHP ในเล่มรายงาน (ตารางที่ 11, CR = 0.086)
AHP_WEIGHTS_FROM_THESIS = {
    "soil": 0.205, "water": 0.309, "rainfall": 0.336,
    "drought": 0.040, "flood": 0.044, "transport": 0.065,
}

# ปัจจัยที่ "ค่าดิบยิ่งน้อยยิ่งดี" (Cost Criteria ตามหัวข้อ 2.5 ของเล่ม)
# เช่น ระยะห่างจากแหล่งน้ำ ยิ่งใกล้ยิ่งเหมาะสม -> ต้องกลับค่าก่อนใช้เป็นคะแนน
COST_FACTORS = {"water", "transport", "drought", "flood"}


def generate_synthetic_layer(factor_name: str) -> np.ndarray:
    """สร้างข้อมูลจำลองสำหรับปัจจัยหนึ่งๆ (ใช้ชั่วคราวตอนยังไม่ได้อัปโหลดไฟล์จริง)

    ปรับให้แต่ละปัจจัยมีแพทเทิร์นเชิงพื้นที่ที่สมเหตุสมผลตามความหมายจริงของปัจจัย
    นั้นๆ (อ้างอิงทิศทางการกระจายตัวจากภาพที่ 4-8 ในเล่มรายงาน) แทนที่จะใช้สูตร
    sin/cos สุ่มเหมือนกันหมดทุกปัจจัย ซึ่งทำให้แผนที่ผลลัพธ์ไม่มีความหมาย

    *** ยังเป็นข้อมูลจำลอง ไม่ใช่ข้อมูลจริง *** ใช้เพื่อทดสอบระบบและสาธิตเท่านั้น
    เมื่อได้ข้อมูลจริงตามตารางที่ 2 ของเล่มแล้ว ให้อัปโหลดทับผ่านหน้าเว็บ
    """
    LON, LAT = _grid_lonlat()

    # จุดอ้างอิงจำลอง (พิกัดโดยประมาณของสถานที่จริงในจังหวัดขอนแก่น)
    WATER_POINTS = [(102.83, 16.55), (102.45, 16.70), (102.95, 16.30)]  # อ่างอุบลรัตน์ + ลำน้ำพอง
    FACTORY_POINTS = [(102.4284, 16.4881), (102.8400, 16.7316)]          # มิตรภูเวียง + ขอนแก่น (KSL)

    def _dist_to_nearest(points):
        d = np.full(LON.shape, np.inf)
        for plon, plat in points:
            d = np.minimum(d, np.sqrt((LON - plon) ** 2 + (LAT - plat) ** 2))
        return d

    rng = np.random.default_rng(zlib.crc32(factor_name.encode("utf-8")))
    noise = rng.normal(0, 0.03, LON.shape)

    if factor_name == "water":
        raw = -_dist_to_nearest(WATER_POINTS)          # ใกล้แหล่งน้ำ = ดี
    elif factor_name == "transport":
        raw = -_dist_to_nearest(FACTORY_POINTS)        # ใกล้โรงงาน/ถนน = ดี
    elif factor_name == "rainfall":
        # ไล่ระดับจากตะวันตกเฉียงเหนือ (แล้ง) ไปตะวันออกเฉียงใต้ (ฝนชุก) ตามภาพที่ 5
        lon01 = (LON - LON.min()) / (LON.max() - LON.min())
        lat01 = (LAT - LAT.min()) / (LAT.max() - LAT.min())
        raw = lon01 * 0.6 + (1 - lat01) * 0.4
    elif factor_name == "drought":
        raw = np.sqrt((LON - 102.55) ** 2 + (LAT - 16.55) ** 2)   # ไกลโซนแล้ง = ดี
    elif factor_name == "flood":
        raw = np.sqrt((LON - 102.75) ** 2 + (LAT - 16.65) ** 2)   # ไกลโซนน้ำท่วม = ดี
    elif factor_name == "soil":
        raw = np.sin(LON * 15) * np.cos(LAT * 12)                  # กระจายเป็นหย่อมชุดดิน
    else:
        raw = np.sin(LON * 8) * np.cos(LAT * 6)

    return _normalize_masked(raw + noise)

def apply_classification(raw: np.ndarray, breaks: list[dict]) -> np.ndarray:
    if not breaks:
        return _normalize_masked(raw)

    scored = np.full(raw.shape, np.nan)
    for b in breaks:
        lo, hi, score = float(b["min"]), float(b["max"]), float(b["score"])
        mask = (raw >= lo) & (raw <= hi)
        scored = np.where(mask, score, scored)

    min_score = min(float(b["score"]) for b in breaks)
    max_score = max(float(b["score"]) for b in breaks)
    scored = np.where(np.isnan(scored), min_score, scored)

    if max_score <= 0:
        return np.zeros_like(scored)
    return scored / max_score

def default_classification_breaks(raw: np.ndarray, n_classes: int = 4) -> list[dict]:
    lo, hi = float(np.min(raw)), float(np.max(raw))
    if hi - lo < 1e-9:
        hi = lo + 1.0
    edges = np.linspace(lo, hi, n_classes + 1)
    scores = np.linspace(1, 4, n_classes)
    breaks = []
    for i in range(n_classes):
        breaks.append({
            "min": round(float(edges[i]), 4),
            "max": round(float(edges[i + 1]), 4),
            "score": round(float(scores[i]), 1),
        })
    return breaks

def get_layer(factor_name: str) -> np.ndarray:
    if factor_name in classification_tables and factor_name in raw_layers:
        return apply_classification(raw_layers[factor_name], classification_tables[factor_name])
    if factor_name in uploaded_layers:
        return uploaded_layers[factor_name]
    return generate_synthetic_layer(factor_name)

def get_layer_source(factor_name: str) -> str:
    if factor_name in classification_tables and factor_name in raw_layers:
        return "classified"
    if factor_name in uploaded_layers:
        return "uploaded"
    return "synthetic"

def layer_to_rgba(score: np.ndarray) -> np.ndarray:
    """สีสำหรับ 'ชั้นข้อมูลดิบรายปัจจัย' (โทนน้ำเงินอ่อน->เข้ม) แยกจากสีผลลัพธ์ suitability
    แก้ไข: (1) ลด alpha พื้นฐานลงเล็กน้อยให้เห็นแผนที่ฐานทะลุขึ้นมาชัดกว่าเดิม
    (2) ตัดพื้นที่นอกขอบเขตจังหวัดขอนแก่นจริงให้โปร่งใส (alpha=0) แทนที่จะ
    ระบายสีเต็มกรอบสี่เหลี่ยม ทำให้เห็นเป็นรูปทรงจังหวัดจริงบนแผนที่"""
    r = np.clip(0.85 - score * 0.65, 0, 1)
    g = np.clip(0.90 - score * 0.55, 0, 1)
    b = np.full_like(score, 0.95)
    a = np.full_like(score, 0.55)
    rgba = np.stack([r, g, b, a], axis=-1)
    rgba_u8 = (rgba * 255).astype(np.uint8)
    rgba_u8[~get_province_mask(), 3] = 0
    return rgba_u8

def score_to_rgba(score: np.ndarray) -> np.ndarray:
    """สีสำหรับ 'ผลลัพธ์ความเหมาะสมสุดท้าย' แดง(ไม่เหมาะสม) -> เหลือง -> เขียว(เหมาะสมมาก)
    แก้ไข: ลด alpha + ตัดพื้นที่นอกจังหวัดให้โปร่งใส เช่นเดียวกับ layer_to_rgba"""
    r = np.clip(2 * (1 - score), 0, 1)
    g = np.clip(2 * score, 0, 1)
    b = np.zeros_like(score)
    a = np.full_like(score, 0.60)
    rgba = np.stack([r, g, b, a], axis=-1)
    rgba_u8 = (rgba * 255).astype(np.uint8)
    rgba_u8[~get_province_mask(), 3] = 0
    return rgba_u8

def array_to_png_base64(rgba: np.ndarray) -> str:
    img = Image.fromarray(rgba, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def bounds_list() -> list[float]:
    b = KHONKAEN_BOUNDS
    return [b["west"], b["south"], b["east"], b["north"]]

# ==================================================================
# การจำแนกความเหมาะสม 4 ระดับตามมาตรฐาน FAO (S1, S2, S3, N)
# อ้างอิงเล่มรายงาน หัวข้อ 2.2 และวัตถุประสงค์ข้อ 1.2.2 ที่ระบุว่าระบบต้อง
# "แสดงผลพื้นที่ที่มีความเหมาะสมแบบ 4 ระดับ (S1, S2, S3, N)"
#
# หมายเหตุสำคัญ: เล่มรายงานกำหนดเกณฑ์คะแนน "รายปัจจัย" ไว้ครบ (ตารางที่ 4-9)
# แต่ *ไม่ได้ระบุ* เกณฑ์แบ่งช่วงของ "คะแนนรวม" ว่าเท่าไรถึงเป็น S1/S2/S3/N
# ควรยืนยันกับอาจารย์ที่ปรึกษาว่าจะใช้เกณฑ์นี้ หรือเปลี่ยนเป็น Natural Breaks
#
# ⚠️ ค่า min/max ด้านล่างต้องตรงกับเกณฑ์ใน geoserver_publish.write_result_geotiff()
# เสมอ ไม่งั้นภาพบนหน้าเว็บกับเลเยอร์ WMS ที่ GeoServer เสิร์ฟจะจำแนกคนละแบบ
# (แก้ไข: เดิมฝั่งภาพใช้ 0.25/0.50/0.75 แต่ฝั่ง GeoServer ใช้ 0.40/0.55/0.70
#  ทำให้ผลลัพธ์ 2 ที่ไม่ตรงกัน — ปรับให้ใช้ชุดเดียวกันคือ 0.40/0.55/0.70)
# ==================================================================
FAO_CLASSES = [
    # ใช้สีเขียวสว่าง (#55FF00) สำหรับ S1
    {"code": 4, "cls": "S1", "label": "เหมาะสมสูง",       "color": "#55FF00", "min": 3.50, "max": 4.01},
    # ใช้สีเหลือง (#FFFF00) สำหรับ S2
    {"code": 3, "cls": "S2", "label": "เหมาะสมปานกลาง",   "color": "#FFFF00", "min": 2.50, "max": 3.50},
    # ใช้สีส้ม (#FFAA00) สำหรับ S3
    {"code": 2, "cls": "S3", "label": "เหมาะสมน้อย",      "color": "#FFAA00", "min": 1.50, "max": 2.50},
    # ใช้สีแดง (#FF0000) สำหรับ N
    {"code": 1, "cls": "N",  "label": "ไม่เหมาะสม",        "color": "#FF0000", "min": -0.01, "max": 1.50},
]


def classify_fao(score: np.ndarray) -> np.ndarray:
    """แปลงคะแนนรวมต่อเนื่อง (0-1) เป็นรหัสชั้นความเหมาะสม FAO (1=N ... 4=S1)"""
    out = np.ones(score.shape, dtype=np.int16)
    for c in FAO_CLASSES:
        out = np.where((score >= c["min"]) & (score < c["max"]), c["code"], out)
    return out


def fao_to_rgba(class_code: np.ndarray) -> np.ndarray:
    """ระบายสีแบบ 4 ระดับไม่ต่อเนื่อง (ตามมาตรฐาน FAO) แทนการไล่สีต่อเนื่อง
    เพื่อให้ตรงกับที่เล่มรายงานกำหนด และตรงกับ legend/SLD ของ GeoServer"""
    h, w = class_code.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    for c in FAO_CLASSES:
        hx = c["color"].lstrip("#")
        r, g, b = (int(hx[i:i + 2], 16) for i in (0, 2, 4))
        rgba[class_code == c["code"]] = [r, g, b, 200]
    rgba[~get_province_mask(), 3] = 0
    return rgba


_cell_area_cache = None


def cell_area_km2() -> np.ndarray:
    """พื้นที่จริงของแต่ละ cell (ตร.กม.) — ขนาดตามละติจูด (1 องศา lon สั้นลงเมื่อ
    ห่างจากเส้นศูนย์สูตร) ใช้แปลงจำนวน cell เป็นพื้นที่ ไร่ สำหรับตารางสรุป"""
    global _cell_area_cache
    if _cell_area_cache is not None:
        return _cell_area_cache
    _, LAT = _grid_lonlat()
    dlon = (KHONKAEN_BOUNDS["east"] - KHONKAEN_BOUNDS["west"]) / (GRID_WIDTH - 1)
    dlat = (KHONKAEN_BOUNDS["north"] - KHONKAEN_BOUNDS["south"]) / (GRID_HEIGHT - 1)
    _cell_area_cache = (dlon * 111.32 * np.cos(np.radians(LAT))) * (dlat * 110.57)
    return _cell_area_cache


def fao_area_summary(class_code: np.ndarray) -> list[dict]:
    """สรุปพื้นที่ (ไร่ และ ร้อยละ) แยกตามระดับความเหมาะสม เฉพาะในเขตจังหวัดจริง
    1 ตร.กม. = 625 ไร่"""
    mask = get_province_mask()
    areas = cell_area_km2()
    total_km2 = float(areas[mask].sum())
    rows = []
    for c in FAO_CLASSES:
        sel = mask & (class_code == c["code"])
        km2 = float(areas[sel].sum())
        rows.append({
            "cls": c["cls"],
            "label": c["label"],
            "color": c["color"],
            "rai": round(km2 * 625, 0),
            "km2": round(km2, 2),
            "percent": round(km2 / total_km2 * 100, 2) if total_km2 > 0 else 0.0,
        })
    return rows




@app.get("/api/layer-preview")
def layer_preview(factor: str):
    layer = get_layer(factor)
    return {
        "status": "success",
        "factor": factor,
        "source": get_layer_source(factor),
        "has_raw": factor in raw_layers,
        "preview_image_base64": array_to_png_base64(layer_to_rgba(layer)),
        "bounds": bounds_list(),
    }

@app.post("/api/upload-layer")
async def upload_layer(factor: str = Form(...), file: UploadFile = File(...)):
    filename = (file.filename or "").lower()
    content = await file.read()

    if filename.endswith((".tif", ".tiff")):
        raw, coverage_pct = _read_geotiff_to_grid(content)
    elif filename.endswith((".geojson", ".json")):
        raw = _read_geojson_to_grid(content)
        coverage_pct = 100.0
    elif filename.endswith(".zip"):
        raw = _read_shapefile_zip_to_grid(content)
        coverage_pct = 100.0
    else:
        raise HTTPException(400, "รองรับเฉพาะไฟล์ .tif, .geojson หรือบีบอัด Shapefile เป็น .zip เท่านั้น")

    raw_layers[factor] = raw
    # normalize จากเฉพาะพื้นที่ในจังหวัด: ไฟล์จริงมักครอบคลุมกว้างกว่าจังหวัด
    # (เช่นทั้งภาคอีสาน) ถ้าคิดจากทั้งกรอบ ค่า 0-1 จะเพี้ยนตามข้อมูลนอกพื้นที่ศึกษา
    uploaded_layers[factor] = raw #_normalize_masked(raw)
    classification_tables.pop(factor, None)

    return {
        "status": "success",
        "factor": factor,
        "source": "uploaded",
        "raw_min": round(float(raw.min()), 4),
        "raw_max": round(float(raw.max()), 4),
        "coverage_percent": round(coverage_pct, 1),
        "preview_image_base64": array_to_png_base64(layer_to_rgba(uploaded_layers[factor])),
        "bounds": bounds_list(),
    }

def _read_geotiff_to_grid(content: bytes) -> tuple[np.ndarray, float]:
    try:
        import rasterio
        from rasterio.io import MemoryFile
        from rasterio.transform import from_bounds
        from rasterio.warp import Resampling, reproject
    except ImportError as exc:
        raise HTTPException(500, "ต้องติดตั้งไลบรารี rasterio ก่อน") from exc

    dst_transform = from_bounds(
        KHONKAEN_BOUNDS["west"], KHONKAEN_BOUNDS["south"],
        KHONKAEN_BOUNDS["east"], KHONKAEN_BOUNDS["north"],
        GRID_WIDTH, GRID_HEIGHT,
    )
    destination = np.zeros((GRID_HEIGHT, GRID_WIDTH), dtype=np.float64)

    with MemoryFile(content) as memfile:
        with memfile.open() as src:
            src_band = src.read(1, masked=True).astype("float64")
            src_crs = src.crs or "EPSG:4326"

            reproject(
                source=src_band.filled(np.nan),
                destination=destination,
                src_transform=src.transform,
                src_crs=src_crs,
                dst_transform=dst_transform,
                dst_crs="EPSG:4326",
                resampling=Resampling.bilinear,
                src_nodata=np.nan,
                dst_nodata=np.nan,
            )

    valid_mask = ~np.isnan(destination)
    coverage_pct = float(valid_mask.mean() * 100)

    if np.isnan(destination).any():
        fill_value = np.nanmean(destination) if not np.all(np.isnan(destination)) else 0.0
        destination = np.nan_to_num(destination, nan=fill_value)

    return destination, coverage_pct

def _read_geojson_to_grid(content: bytes) -> np.ndarray:
    try:
        from shapely.geometry import shape
        from shapely.ops import unary_union
        import shapely
    except ImportError as exc:
        raise HTTPException(500, "ต้องติดตั้งไลบรารี shapely ก่อน") from exc

    try:
        geojson_data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "ไฟล์ GeoJSON ไม่ถูกต้อง (parse ไม่ผ่าน)") from exc

    features = geojson_data.get("features", [geojson_data])
    geoms = [shape(f["geometry"]) for f in features if f.get("geometry")]
    if not geoms:
        raise HTTPException(400, "ไม่พบรูปทรง (geometry) ในไฟล์ GeoJSON")

    merged = unary_union(geoms)
    LON, LAT = _grid_lonlat()
    points = shapely.points(LON.ravel(), LAT.ravel())
    distances_deg = shapely.distance(points, merged).reshape(LON.shape)
    
    KM_PER_DEGREE = 111.32
    return distances_deg * KM_PER_DEGREE

def _read_shapefile_zip_to_grid(content: bytes) -> np.ndarray:
    try:
        import geopandas as gpd
        import shapely
        from shapely.ops import unary_union
    except ImportError as exc:
        raise HTTPException(500, "ต้องติดตั้งไลบรารี geopandas ก่อน (pip install geopandas)") from exc

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "upload.zip")
        with open(zip_path, "wb") as f:
            f.write(content)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(tmpdir)
        
        shp_files = [f for f in os.listdir(tmpdir) if f.endswith('.shp')]
        if not shp_files:
            raise HTTPException(400, "ไม่พบไฟล์ .shp ภายในไฟล์ ZIP ที่อัปโหลด")
        
        shp_path = os.path.join(tmpdir, shp_files[0])
        gdf = gpd.read_file(shp_path)
        
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)
            
        geoms = gdf.geometry.dropna().tolist()
        if not geoms:
            raise HTTPException(400, "ไฟล์ Shapefile ไม่มีข้อมูลรูปทรง (Geometry)")
            
        merged = unary_union(geoms)
        LON, LAT = _grid_lonlat()
        points = shapely.points(LON.ravel(), LAT.ravel())
        distances_deg = shapely.distance(points, merged).reshape(LON.shape)
        
        KM_PER_DEGREE = 111.32
        return distances_deg * KM_PER_DEGREE

class ClassBreak(BaseModel):
    min: float
    max: float
    score: float

class ClassificationRequest(BaseModel):
    factor: str
    breaks: list[ClassBreak]

    @field_validator("breaks")
    @classmethod
    def check_not_empty(cls, v):
        if not v:
            raise ValueError("ต้องมีอย่างน้อย 1 ช่วงเกณฑ์คะแนน")
        return v

@app.get("/api/layer-classification")
def get_layer_classification(factor: str):
    if factor not in raw_layers:
        raise HTTPException(400, "ปัจจัยนี้ยังไม่มีไฟล์ข้อมูลจริง กรุณาอัปโหลดไฟล์ก่อน")
    raw = raw_layers[factor]
    is_saved = factor in classification_tables
    breaks = classification_tables[factor] if is_saved else default_classification_breaks(raw)

    return {
        "status": "success",
        "factor": factor,
        "is_saved": is_saved,
        "raw_min": round(float(raw.min()), 4),
        "raw_max": round(float(raw.max()), 4),
        "breaks": breaks,
    }

@app.post("/api/set-classification")
def set_classification(data: ClassificationRequest):
    if data.factor not in raw_layers:
        raise HTTPException(400, "ปัจจัยนี้ยังไม่มีไฟล์ข้อมูลจริง กรุณาอัปโหลดไฟล์ก่อนตั้งเกณฑ์คะแนน")

    breaks = [b.model_dump() for b in data.breaks]
    classification_tables[data.factor] = breaks
    classified = apply_classification(raw_layers[data.factor], breaks)

    return {
        "status": "success",
        "factor": data.factor,
        "source": "classified",
        "preview_image_base64": array_to_png_base64(layer_to_rgba(classified)),
        "bounds": bounds_list(),
    }

@app.post("/api/reset-layers")
def reset_layers():
    raw_layers.clear()
    uploaded_layers.clear()
    classification_tables.clear()
    last_suitability_result["array"] = None
    return {"status": "success", "message": "ล้างข้อมูลทั้งหมดแล้ว"}

@app.get("/api/factors")
def get_factors():
    """คืน 6 ปัจจัยหลักตามเล่มรายงาน พร้อมชื่อไทยและน้ำหนักอ้างอิงจาก AHP
    (ตารางที่ 11) — หน้าเว็บเรียกตอนโหลดครั้งแรกเพื่อให้ชื่อปัจจัยตรงกับ backend เสมอ"""
    return {
        "status": "success",
        "factors": [
            {"key": k, "label": FACTOR_LABELS_TH[k],
             "thesis_weight": AHP_WEIGHTS_FROM_THESIS[k]}
            for k in FACTOR_ORDER
        ],
    }


@app.get("/api/geoserver-status")
def geoserver_status():
    """ตรวจสอบว่าเชื่อมต่อ GeoServer ได้หรือไม่ (ใช้แสดงสถานะบนหน้าเว็บ)"""
    return {"status": "success", **gs.check_status()}


@app.get("/api/layers-status")
def layers_status():
    """คืนรายชื่อปัจจัยที่มีข้อมูลจริงอยู่แล้วในระบบ ณ ขณะนี้ (อัปโหลดเอง +
    โหลดล่วงหน้า เช่น โรงงานน้ำตาล) — ใช้ตอนโหลดหน้าเว็บครั้งแรก"""
    return {"status": "success", "factors_with_raw_data": list(raw_layers.keys())}


@app.get("/api/suitability-value")
def suitability_value(lon: float, lat: float):
    """รับพิกัดที่คลิกบนแผนที่ คืนคะแนนความเหมาะสม ณ จุดนั้นจากผลลัพธ์ล่าสุด"""
    if last_suitability_result.get("array") is None:
        raise HTTPException(400, "ยังไม่มีผลลัพธ์ กรุณากดคำนวณแผนที่ก่อน")

    arr = last_suitability_result["array"]
    col_frac = (lon - KHONKAEN_BOUNDS["west"]) / (KHONKAEN_BOUNDS["east"] - KHONKAEN_BOUNDS["west"])
    row_frac = (KHONKAEN_BOUNDS["north"] - lat) / (KHONKAEN_BOUNDS["north"] - KHONKAEN_BOUNDS["south"])
    col = max(0, min(GRID_WIDTH - 1, int(round(col_frac * (GRID_WIDTH - 1)))))
    row = max(0, min(GRID_HEIGHT - 1, int(round(row_frac * (GRID_HEIGHT - 1)))))

    score = float(arr[row, col])

    # ใช้เกณฑ์ FAO ชุดเดียวกับที่ใช้ระบายสีแผนที่และตารางสรุป (FAO_CLASSES)
    # แก้ไข: เดิมมีเกณฑ์ของตัวเอง (0.7/0.4 -> 3 ระดับ ชื่อ "เหมาะสมมาก") ซึ่งไม่ตรง
    # กับ 4 ระดับ S1/S2/S3/N ที่แสดงบนแผนที่ ทำให้คลิกจุดเดียวกันได้คำตอบคนละแบบ
    matched = next((c for c in FAO_CLASSES if c["min"] <= score < c["max"]), FAO_CLASSES[-1])
    outside = not bool(get_province_mask()[row, col])

    return {"status": "success", "lon": round(lon, 5), "lat": round(lat, 5),
            "score": round(score, 4),
            "cls": matched["cls"],
            "label": matched["label"],
            "color": matched["color"],
            "outside_province": outside}

class SuitabilityRequest(BaseModel):
    weights: dict[str, float]

@app.post("/api/suitability")
def calculate_suitability(data: SuitabilityRequest):
    if not data.weights:
        raise HTTPException(400, "ไม่มีข้อมูลน้ำหนัก (weights)")

    suitability = np.zeros((GRID_HEIGHT, GRID_WIDTH))
    layer_sources = {}
    for factor, weight in data.weights.items():
        suitability += get_layer(factor) * weight
        layer_sources[factor] = get_layer_source(factor)

    # normalize จากเฉพาะพื้นที่ในจังหวัดจริง (ดูเหตุผลที่ _normalize_masked)
    #suitability = _normalize_masked(suitability)

    # บันทึกผลลัพธ์ไว้สำหรับการดาวน์โหลด
    last_suitability_result["array"] = suitability
    
    image_base64 = array_to_png_base64(score_to_rgba(suitability))

    # --- จำแนก 4 ระดับตามมาตรฐาน FAO (S1/S2/S3/N) ตามวัตถุประสงค์ข้อ 1.2.2 ---
    fao_class = classify_fao(suitability)
    last_suitability_result["fao_class"] = fao_class
    fao_image_base64 = array_to_png_base64(fao_to_rgba(fao_class))
    fao_summary = fao_area_summary(fao_class)

    # --- เขียนผลลัพธ์เป็น GeoTIFF แล้วเผยแพร่ผ่าน GeoServer (ถ้าเปิดใช้งาน) ---
    province_mask = get_province_mask()

    # ---- เผยแพร่ผลลัพธ์ขึ้น GeoServer (ตามแนวทาง Phase 2 ในคลิปเสียงอาจารย์) ----
    # ถ้า GeoServer ปิดอยู่/ต่อไม่ติด จะไม่ทำให้ระบบล่ม แค่คืน published=false
    # แล้วหน้าเว็บจะใช้ภาพ PNG (image_base64) แสดงผลแทนตามเดิม
    geoserver_info = {"published": False, "reason": "disabled"}
    try:
        tif_path = gs.write_result_geotiff(suitability, province_mask, KHONKAEN_BOUNDS)
        geoserver_info = gs.publish(tif_path)
        geoserver_info["tif_path"] = str(tif_path)
    except Exception as e:
        geoserver_info = {"published": False, "reason": f"{type(e).__name__}: {e}"}

    # แก้บั๊ก: เดิมคิด % จากทั้งกรอบสี่เหลี่ยม ซึ่ง ~64% เป็นพื้นที่นอกจังหวัด
    # (ที่ถูกซ่อนไม่ให้เห็นบนแผนที่อยู่แล้ว) ทำให้ตัวเลขที่รายงานผิดจากความจริงมาก
    # เช่น พื้นที่เหมาะสมสูงรายงาน 21% ทั้งที่ของจริงในจังหวัดคือ ~34%
    inside = suitability[province_mask]

    pct_high = float(np.mean(inside >= 0.7) * 100)
    pct_mid = float(np.mean((inside >= 0.4) & (inside < 0.7)) * 100)
    pct_low = float(np.mean(inside < 0.4) * 100)

    n_classified = sum(1 for s in layer_sources.values() if s == "classified")
    n_uploaded = sum(1 for s in layer_sources.values() if s == "uploaded")
    n_synthetic = sum(1 for s in layer_sources.values() if s == "synthetic")
    note = f"ปัจจัยที่จัดกลุ่มคะแนนเอง {n_classified} | ไฟล์จริง {n_uploaded} | ข้อมูลจำลอง {n_synthetic}"

    return {
        "status": "success",
        "image_base64": image_base64,
        "fao_image_base64": fao_image_base64,
        "fao_summary": fao_summary,
        "fao_classes": FAO_CLASSES,
        "bounds": bounds_list(),
        "layer_sources": layer_sources,
        "geoserver": geoserver_info,
        "stats": {
            "mean_score": round(float(inside.mean()), 4),
            "min_score": round(float(inside.min()), 4),
            "max_score": round(float(inside.max()), 4),
            "percent_high_suitability": round(pct_high, 2),
            "percent_medium_suitability": round(pct_mid, 2),
            "percent_low_suitability": round(pct_low, 2),
        },
        "note": note,
    }

# API สำหรับดาวน์โหลดแผนที่ผลลัพธ์เป็นไฟล์ต่างๆ
@app.get("/api/download")
def download_result(type: str):
    if last_suitability_result.get("array") is None:
        raise HTTPException(400, "ยังไม่มีผลลัพธ์ กรุณากดคำนวณแผนที่ก่อน")

    # ✅ ดึงแผนที่ที่ตัดเกรดเป็น 1, 2, 3, 4 มาใช้เลย (ไม่ต้องเอาคะแนนดิบไปคูณ 100)
    fao_array = last_suitability_result["fao_class"]
    
    h, w = fao_array.shape
    suit_int = fao_array.astype(np.int32)
    
    # ใช้ mask พื้นที่ขนาดเต็ม
    mask_full = get_province_mask()
    suit_int[~mask_full] = -1

    try:
        from rasterio.transform import from_bounds
        import rasterio.features
        import geopandas as gpd
        import fiona
    except ImportError as exc:
        raise HTTPException(500, "กรุณาติดตั้งแพ็กเกจ: pip install rasterio geopandas fiona shapely") from exc

    # เปิดการเขียนไฟล์ KML
    fiona.drvsupport.supported_drivers['KML'] = 'rw'
    
    # ดึงค่าขนาด w, h แบบเต็มมาใช้
    transform = from_bounds(
        KHONKAEN_BOUNDS["west"], KHONKAEN_BOUNDS["south"],
        KHONKAEN_BOUNDS["east"], KHONKAEN_BOUNDS["north"],
        w, h,
    )

    # แปลง Grid เป็นรูปหลายเหลี่ยม (Polygon)
    shapes_gen = rasterio.features.shapes(suit_int, transform=transform)
    records = [{"geometry": geom, "properties": {"score": val}} for geom, val in shapes_gen]
    gdf = gpd.GeoDataFrame.from_features(records, crs="EPSG:4326")
    gdf = gdf[gdf["score"] > 0] # เอาเฉพาะพื้นที่ที่มีคะแนน

    buf = io.BytesIO()
    
    if type == "GeoJSON":
        # เขียนผ่านไฟล์ชั่วคราวก่อน (แทนเขียนตรงไปที่ BytesIO) เพื่อความเข้ากันได้
        # ที่แน่นอนกว่ากับทุกเวอร์ชันของ fiona/geopandas
        with tempfile.TemporaryDirectory() as tmpdir:
            geojson_path = os.path.join(tmpdir, "suitability_map.geojson")
            gdf.to_file(geojson_path, driver="GeoJSON")
            with open(geojson_path, "rb") as f:
                buf.write(f.read())
        filename = "suitability_map.geojson"
        media_type = "application/geo+json"
        
    elif type == "Shapefile":
        with tempfile.TemporaryDirectory() as tmpdir:
            shp_path = os.path.join(tmpdir, "suitability_map.shp")
            gdf.to_file(shp_path, driver="ESRI Shapefile")
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname in os.listdir(tmpdir):
                    zf.write(os.path.join(tmpdir, fname), fname)
        filename = "suitability_map_shp.zip"
        media_type = "application/zip"
        
    elif type == "CSV":
        gdf["longitude"] = gdf.geometry.centroid.x
        gdf["latitude"] = gdf.geometry.centroid.y
        gdf.drop(columns="geometry").to_csv(buf, index=False)
        filename = "suitability_map.csv"
        media_type = "text/csv"
        
    elif type == "KML":
        with tempfile.TemporaryDirectory() as tmpdir:
            kml_path = os.path.join(tmpdir, "suitability_map.kml")
            gdf.to_file(kml_path, driver="KML")
            with open(kml_path, "rb") as f:
                buf.write(f.read())
        filename = "suitability_map.kml"
        media_type = "application/vnd.google-earth.kml+xml"
        
    else:
        raise HTTPException(400, "ยังไม่รองรับไฟล์รูปแบบนี้")

    buf.seek(0)
    return StreamingResponse(
        buf, 
        media_type=media_type, 
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
