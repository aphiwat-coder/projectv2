"""
geoserver_publish.py
====================
เชื่อมต่อ GeoServer ตามแนวทางที่อาจารย์แนะนำในคลิปเสียง (Phase 2: Map Server)

หน้าที่:
  1. เขียนผลลัพธ์ความเหมาะสมเป็นไฟล์ GeoTIFF (.tif) พร้อมระบบพิกัดจริง
  2. สั่ง GeoServer ผ่าน REST API ให้ publish ไฟล์นั้นเป็นเลเยอร์ WMS
  3. ตั้งสไตล์ (SLD) ไล่สีตามระดับความเหมาะสม FAO (S1/S2/S3/N)

หลักการสำคัญ — "ต่อไม่ติดต้องไม่ล่ม":
ทุกฟังก์ชันในไฟล์นี้จะไม่ throw exception ออกไปข้างนอก ถ้า GeoServer ปิดอยู่
หรือต่อไม่ได้ จะคืนสถานะ error กลับไปเฉยๆ แล้วระบบหลักจะใช้ภาพ PNG แบบเดิม
แสดงผลต่อไปได้ตามปกติ (graceful fallback) — เพื่อให้พัฒนา/สาธิตได้แม้ยังไม่ได้
เปิด GeoServer

การตั้งค่า: ใช้ environment variable (ดูตัวอย่างใน backend/.env.example)
ถ้าไม่ตั้งอะไรเลย ระบบจะปิดการใช้ GeoServer โดยอัตโนมัติ (GEOSERVER_ENABLED=false)
"""

import os
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------- การตั้งค่า

def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


GEOSERVER_ENABLED = _env_bool("GEOSERVER_ENABLED", "false")
GEOSERVER_URL = os.getenv("GEOSERVER_URL", "http://localhost:8080/geoserver").rstrip("/")
GEOSERVER_USER = os.getenv("GEOSERVER_USER", "admin")
GEOSERVER_PASS = os.getenv("GEOSERVER_PASS", "geoserver")
GEOSERVER_WORKSPACE = os.getenv("GEOSERVER_WORKSPACE", "sugarcane")
GEOSERVER_STORE = os.getenv("GEOSERVER_STORE", "suitability_store")
GEOSERVER_LAYER = os.getenv("GEOSERVER_LAYER", "suitability_result")
GEOSERVER_STYLE = os.getenv("GEOSERVER_STYLE", "suitability_fao")

# โฟลเดอร์ที่จะเขียนไฟล์ .tif ลงไป — ต้องเป็นพาธที่เครื่อง GeoServer อ่านได้
# ถ้าไม่ตั้ง จะใช้ backend/output/ ในโปรเจกต์นี้ (เหมาะกับกรณีรันบนเครื่องเดียวกัน)
_DEFAULT_OUT = Path(__file__).parent / "output"
GEOSERVER_DATA_DIR = Path(os.getenv("GEOSERVER_DATA_DIR", str(_DEFAULT_OUT)))

RESULT_TIF_NAME = "suitability_result.tif"

TIMEOUT = 5  # วินาที — สั้นๆ เพื่อไม่ให้หน้าเว็บค้างรอตอน GeoServer ไม่ได้เปิด


def _auth():
    return (GEOSERVER_USER, GEOSERVER_PASS)


# ------------------------------------------------- 1) เขียนผลลัพธ์เป็น GeoTIFF

def write_result_geotiff(
    suitability: np.ndarray,
    province_mask: np.ndarray,
    bounds: dict,
) -> Path:
    """
    เขียนผลลัพธ์เป็นไฟล์ GeoTIFF พร้อมระบบพิกัด EPSG:4326

    เก็บค่าเป็น "รหัสชั้นความเหมาะสม" 1-4 ตามมาตรฐาน FAO (ไม่ใช่คะแนนทศนิยม)
    เพื่อให้ตั้งสไตล์ SLD แบบ intervals ได้ตรงไปตรงมา:
        4 = S1 เหมาะสมสูง      (คะแนน >= 0.70)
        3 = S2 เหมาะสมปานกลาง  (0.55 - 0.70)
        2 = S3 เหมาะสมน้อย     (0.40 - 0.55)
        1 = N  ไม่เหมาะสม      (< 0.40)
        0 = NoData (นอกขอบเขตจังหวัดขอนแก่น) -> โปร่งใสบนแผนที่

    คืนค่า: พาธเต็มของไฟล์ที่เขียน
    """
    from rasterio.transform import from_bounds
    import rasterio

    cls = np.zeros(suitability.shape, dtype=np.uint8)
    cls[suitability < 0.40] = 1
    cls[(suitability >= 0.40) & (suitability < 0.55)] = 2
    cls[(suitability >= 0.55) & (suitability < 0.70)] = 3
    cls[suitability >= 0.70] = 4
    cls[~province_mask] = 0  # นอกจังหวัด = NoData

    GEOSERVER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = GEOSERVER_DATA_DIR / RESULT_TIF_NAME

    height, width = cls.shape
    transform = from_bounds(
        bounds["west"], bounds["south"], bounds["east"], bounds["north"], width, height
    )

    with rasterio.open(
        out_path, "w",
        driver="GTiff", height=height, width=width, count=1,
        dtype="uint8", crs="EPSG:4326", transform=transform,
        nodata=0, compress="deflate",
    ) as dst:
        dst.write(cls, 1)

    return out_path


# ------------------------------------------------------ 2) SLD (สไตล์ไล่สี FAO)

SLD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
  xmlns="http://www.opengis.net/sld"
  xmlns:ogc="http://www.opengis.net/ogc"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.opengis.net/sld
  http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>{style}</Name>
    <UserStyle>
      <Title>Sugarcane Land Suitability (FAO)</Title>
      <FeatureTypeStyle>
        <Rule>
          <RasterSymbolizer>
            <Opacity>0.8</Opacity>
            <ColorMap type="values">
              <ColorMapEntry color="#000000" quantity="0" opacity="0" label="NoData"/>
              <ColorMapEntry color="#d73027" quantity="1" label="N - not suitable"/>
              <ColorMapEntry color="#fdae61" quantity="2" label="S3 - marginally suitable"/>
              <ColorMapEntry color="#a6d96a" quantity="3" label="S2 - moderately suitable"/>
              <ColorMapEntry color="#1a9850" quantity="4" label="S1 - highly suitable"/>
            </ColorMap>
          </RasterSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
"""


# ------------------------------------------------------------ 3) เรียก REST API

def check_status() -> dict:
    """ตรวจว่าต่อ GeoServer ได้ไหม (ใช้กับปุ่มตรวจสอบสถานะบนหน้าเว็บ)"""
    if not GEOSERVER_ENABLED:
        return {"enabled": False, "connected": False,
                "message": "ปิดการใช้งาน GeoServer อยู่ (GEOSERVER_ENABLED=false) — ใช้โหมดภาพ PNG"}
    try:
        import requests
    except ImportError:
        return {"enabled": True, "connected": False,
                "message": "ยังไม่ได้ติดตั้งไลบรารี requests (pip install requests)"}
    try:
        r = requests.get(f"{GEOSERVER_URL}/rest/about/version.json",
                         auth=_auth(), timeout=TIMEOUT)
        if r.status_code == 200:
            return {"enabled": True, "connected": True,
                    "url": GEOSERVER_URL, "workspace": GEOSERVER_WORKSPACE,
                    "message": "เชื่อมต่อ GeoServer สำเร็จ"}
        if r.status_code == 401:
            return {"enabled": True, "connected": False,
                    "message": "ต่อ GeoServer ได้ แต่ user/password ไม่ถูกต้อง"}
        return {"enabled": True, "connected": False,
                "message": f"GeoServer ตอบกลับรหัส {r.status_code}"}
    except Exception as e:
        return {"enabled": True, "connected": False,
                "message": f"เชื่อมต่อ {GEOSERVER_URL} ไม่ได้ ({type(e).__name__}) — ตรวจว่าเปิด GeoServer แล้วหรือยัง"}


def _ensure_workspace(requests) -> None:
    r = requests.get(f"{GEOSERVER_URL}/rest/workspaces/{GEOSERVER_WORKSPACE}.json",
                     auth=_auth(), timeout=TIMEOUT)
    if r.status_code == 404:
        requests.post(
            f"{GEOSERVER_URL}/rest/workspaces",
            json={"workspace": {"name": GEOSERVER_WORKSPACE}},
            auth=_auth(), timeout=TIMEOUT,
        )


def _ensure_style(requests) -> None:
    """สร้าง/อัปเดตสไตล์ SLD ให้เป็นเวอร์ชันล่าสุดเสมอ"""
    base = f"{GEOSERVER_URL}/rest/workspaces/{GEOSERVER_WORKSPACE}/styles"
    r = requests.get(f"{base}/{GEOSERVER_STYLE}.json", auth=_auth(), timeout=TIMEOUT)
    if r.status_code == 404:
        requests.post(
            base,
            json={"style": {"name": GEOSERVER_STYLE,
                            "filename": f"{GEOSERVER_STYLE}.sld"}},
            auth=_auth(), timeout=TIMEOUT,
        )
    requests.put(
        f"{base}/{GEOSERVER_STYLE}",
        data=SLD_XML.format(style=GEOSERVER_STYLE).encode("utf-8"),
        headers={"Content-type": "application/vnd.ogc.sld+xml"},
        auth=_auth(), timeout=TIMEOUT,
    )


def publish(tif_path: Path) -> dict:
    """
    สั่ง GeoServer ให้ publish ไฟล์ .tif เป็นเลเยอร์ WMS

    ใช้วิธี "external.geotiff" คือบอก path ของไฟล์ให้ GeoServer ไปอ่านเอง
    (ไม่ได้อัปโหลดตัวไฟล์ข้ามเน็ตเวิร์ก) จึงเร็วและใช้ซ้ำ path เดิมได้ทุกครั้ง
    ที่คำนวณใหม่ — GeoServer จะเห็นข้อมูลใหม่ทันทีโดยไม่ต้องสร้าง store ใหม่

    คืนค่า dict ที่มี wms_url + layer เมื่อสำเร็จ / มี error เมื่อไม่สำเร็จ
    """
    if not GEOSERVER_ENABLED:
        return {"published": False, "reason": "disabled"}

    try:
        import requests
    except ImportError:
        return {"published": False, "reason": "ไม่ได้ติดตั้งไลบรารี requests"}

    try:
        _ensure_workspace(requests)
        _ensure_style(requests)

        # ชี้ store ไปที่ไฟล์ .tif (สร้างใหม่ถ้ายังไม่มี / อัปเดตถ้ามีแล้ว)
        url = (f"{GEOSERVER_URL}/rest/workspaces/{GEOSERVER_WORKSPACE}"
               f"/coveragestores/{GEOSERVER_STORE}/external.geotiff"
               f"?configure=first&coverageName={GEOSERVER_LAYER}")
        r = requests.put(
            url,
            data=tif_path.resolve().as_uri(),  # file:///... ตามรูปแบบที่ GeoServer ต้องการ
            headers={"Content-type": "text/plain"},
            auth=_auth(), timeout=TIMEOUT * 4,  # ขั้นนี้ช้ากว่าขั้นอื่น
        )
        if r.status_code not in (200, 201, 202):
            return {"published": False,
                    "reason": f"publish ไม่สำเร็จ (HTTP {r.status_code}) {r.text[:200]}"}

        # ผูกสไตล์ FAO เข้ากับเลเยอร์
        requests.put(
            f"{GEOSERVER_URL}/rest/layers/{GEOSERVER_WORKSPACE}:{GEOSERVER_LAYER}",
            json={"layer": {"defaultStyle": {"name": GEOSERVER_STYLE,
                                             "workspace": GEOSERVER_WORKSPACE}}},
            auth=_auth(), timeout=TIMEOUT,
        )

        # ล้าง cache ของ GeoWebCache ไม่ให้ค้างภาพเก่า (ถ้าไม่มี GWC ก็ข้ามไป)
        try:
            requests.post(
                f"{GEOSERVER_URL}/gwc/rest/masstruncate",
                data=f"<truncateLayer><layerName>{GEOSERVER_WORKSPACE}:{GEOSERVER_LAYER}</layerName></truncateLayer>",
                headers={"Content-type": "text/xml"},
                auth=_auth(), timeout=TIMEOUT,
            )
        except Exception:
            pass

        return {
            "published": True,
            "wms_url": f"{GEOSERVER_URL}/{GEOSERVER_WORKSPACE}/wms",
            "layer": f"{GEOSERVER_WORKSPACE}:{GEOSERVER_LAYER}",
            "tif_path": str(tif_path),
        }
    except Exception as e:
        return {"published": False,
                "reason": f"{type(e).__name__}: {e} — ตรวจว่าเปิด GeoServer แล้วหรือยัง"}
