/*
==========================================================

Matrix

ไฟล์นี้รับผิดชอบเรื่อง "Pairwise Comparison Matrix" ล้วน ๆ:
- สร้างตาราง HTML ตามรายชื่อปัจจัยที่ผู้ใช้กำหนดเอง (ไม่ตายตัวอีกต่อไป)
- ช่องกรอกค่าน้ำหนักเปลี่ยนจากพิมพ์ตัวเลขอิสระ เป็น "เลือก" จาก
  สเกลมาตรฐานของ Saaty เท่านั้น คือ 1, 3, 5, 7, 9 (และส่วนกลับ)
  เพื่อป้องกันผู้ใช้กรอกค่าที่ไม่มีความหมายในทาง AHP เช่น 4.7, 12 ฯลฯ
- อ่านค่าจากตารางกลับมาเป็น matrix (array 2 มิติ) เพื่อส่งให้ backend

==========================================================
*/

// สเกลมาตรฐาน Saaty: value = ค่าที่จะใช้ในเมทริกซ์, label = คำอธิบายที่ผู้ใช้เห็น
const AHP_SCALE = [
    { value: 9,   label: "9  สำคัญกว่ามากที่สุด" },
    { value: 7,   label: "7  สำคัญกว่ามาก" },
    { value: 5,   label: "5  สำคัญกว่าปานกลาง" },
    { value: 3,   label: "3  สำคัญกว่าเล็กน้อย" },
    { value: 1,   label: "1  สำคัญเท่ากัน" },
    { value: 1/3, label: "1/3  สำคัญน้อยกว่าเล็กน้อย" },
    { value: 1/5, label: "1/5  สำคัญน้อยกว่าปานกลาง" },
    { value: 1/7, label: "1/7  สำคัญน้อยกว่ามาก" },
    { value: 1/9, label: "1/9  สำคัญน้อยกว่ามากที่สุด" },
];

// สร้าง <select> หนึ่งช่องสำหรับเปรียบเทียบ "criteria[i] เทียบกับ criteria[j]"
function buildScaleSelect(i, j) {
    let options = AHP_SCALE.map(opt =>
        `<option value="${opt.value}" ${opt.value === 1 ? "selected" : ""}>${opt.label}</option>`
    ).join("");

    return `<select class="ahp-scale-select" id="cell_${i}_${j}" title="เปรียบเทียบระหว่างสองปัจจัยนี้">
                ${options}
            </select>`;
}

// สร้างตาราง Pairwise Matrix ทั้งหมดจากรายชื่อปัจจัย (criteria) ที่ได้รับมา
// criteria คือ array ของชื่อปัจจัย เช่น ["DEM","Slope","Soil", ...] — ผู้ใช้เพิ่ม/ลบเองได้อย่างอิสระ
function renderMatrixTable(criteria) {
    if (criteria.length < 2) {
        return `<p style="text-align:center; color:#c62828;">
                    ต้องมีปัจจัยอย่างน้อย 2 ตัวจึงจะสร้างตารางเปรียบเทียบได้
                    กรุณาเพิ่มปัจจัยในช่อง "กำหนดปัจจัย (ตัวแปร)" ก่อน
                </p>`;
    }

    // ✅ เพิ่มปุ่มโหลดค่าผู้เชี่ยวชาญตรงนี้
    let html = `
        <div style="text-align: right; margin-bottom: 12px;">
            <button type="button" class="btn btn-outline-green" onclick="fillExpertMatrix()" style="padding: 8px 15px; font-size: 0.85rem;">
                ⚡ โหลดค่าผู้เชี่ยวชาญ (ตามเล่ม)
            </button>
        </div>
    `;

    html += "<table style='width:100%; text-align:center; border-collapse: collapse; margin-bottom: 20px;'><tr><th>ปัจจัย</th>";

    criteria.forEach(c => {
        html += `<th style='padding:10px; border:1px solid #ccc; background:#1b5e20; color:white;' title="${c}">${window.displayLabel ? window.displayLabel(c) : c}</th>`;
    });
    html += "</tr>";

    for (let i = 0; i < criteria.length; i++) {
        html += `<tr><th style='padding:10px; border:1px solid #ccc; background:#1b5e20; color:white;' title="${criteria[i]}">${window.displayLabel ? window.displayLabel(criteria[i]) : criteria[i]}</th>`;

        for (let j = 0; j < criteria.length; j++) {
            if (i === j) {
                html += `<td style='border:1px solid #ccc; background:#e8f5e9; font-weight:bold;'>1</td>`;
            } else if (i < j) {
                html += `<td style='border:1px solid #ccc; padding: 5px;'>${buildScaleSelect(i, j)}</td>`;
            } else {
                // ช่องส่วนกลับ (ฝั่งซ้ายล่าง) คำนวณอัตโนมัติจากฝั่งขวาบน ไม่ต้องกรอกซ้ำ
                html += `<td style='border:1px solid #ccc; background:#f4f7f8; color:#777;' id='cell_${i}_${j}'>ส่วนกลับ (auto)</td>`;
            }
        }
        html += "</tr>";
    }
    html += "</table>";
    return html;
}

// อ่านค่าทั้งตารางกลับมาเป็น matrix (array 2 มิติ) ตามลำดับ criteria ปัจจุบัน
function readMatrixFromDOM(criteria) {
    let matrix = [];
    for (let i = 0; i < criteria.length; i++) {
        let row = [];
        for (let j = 0; j < criteria.length; j++) {
            if (i === j) {
                row.push(1.0);
            } else if (i < j) {
                const el = document.getElementById(`cell_${i}_${j}`);
                const val = el ? parseFloat(el.value) : 1.0;
                row.push(val);
            } else {
                const el = document.getElementById(`cell_${j}_${i}`);
                const val = el ? parseFloat(el.value) : 1.0;
                row.push(1.0 / val);
            }
        }
        matrix.push(row);
    }
    return matrix;
}
// ==========================================================
// ฟังก์ชันสำหรับเติมค่า AHP ตามผู้เชี่ยวชาญ (ตารางที่ 10 ในเล่มรายงาน)
// ลำดับ: ดิน(0), แหล่งน้ำ(1), น้ำฝน(2), ภัยแล้ง(3), น้ำท่วม(4), คมนาคม(5)
// ==========================================================
window.fillExpertMatrix = function() {
    // กำหนดค่าเฉพาะสามเหลี่ยมบน (Upper Triangle)
    const expertValues = {
        "cell_0_1": "1", // ดิน vs แหล่งน้ำ
        "cell_0_2": "1", // ดิน vs น้ำฝน
        "cell_0_3": "5", // ดิน vs ภัยแล้ง
        "cell_0_4": "5", // ดิน vs น้ำท่วม
        "cell_0_5": "1", // ดิน vs คมนาคม

        "cell_1_2": "1", // แหล่งน้ำ vs น้ำฝน
        "cell_1_3": "9", // แหล่งน้ำ vs ภัยแล้ง
        "cell_1_4": "5", // แหล่งน้ำ vs น้ำท่วม
        "cell_1_5": "9", // แหล่งน้ำ vs คมนาคม

        "cell_2_3": "9", // น้ำฝน vs ภัยแล้ง
        "cell_2_4": "9", // น้ำฝน vs น้ำท่วม
        "cell_2_5": "9", // น้ำฝน vs คมนาคม

        "cell_3_4": "1", // ภัยแล้ง vs น้ำท่วม
        "cell_3_5": "1", // ภัยแล้ง vs คมนาคม

        "cell_4_5": "1"  // น้ำท่วม vs คมนาคม
    };

    // วนลูปยัดค่าลงไปใน Dropdown แต่ละช่อง
    for (const [cellId, value] of Object.entries(expertValues)) {
        const selectEl = document.getElementById(cellId);
        if (selectEl) {
            selectEl.value = value;
        }
    }

    // แสดงแจ้งเตือนมุมขวาบนให้ทราบว่าโหลดสำเร็จแล้ว
    if (typeof showToast === "function") {
        showToast("✅ โหลดค่าน้ำหนักตามผู้เชี่ยวชาญเรียบร้อยแล้ว", "success");
    }
};