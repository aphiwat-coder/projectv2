/*
==========================================================

Classify

ไฟล์นี้รับผิดชอบ "การจัดกลุ่มคะแนน (Reclassification)" ต่อปัจจัย
ตามที่อาจารย์อธิบายในคลิป: ผู้ใช้กำหนดเองว่าค่าดิบช่วงไหน = กี่คะแนน
เช่น น้ำฝน 1,000-1,200 มม./ปี = 10 คะแนน แทนการ normalize อัตโนมัติ
ซึ่งทำให้ผู้ใช้แต่ละคน/แต่ละพืชเศรษฐกิจ กำหนดเกณฑ์ของตัวเองได้อิสระ

==========================================================
*/

// วาดตารางเกณฑ์คะแนน (breaks) ของปัจจัยหนึ่งลงใน modal
function renderClassificationForm(factor, breaks, rawMin, rawMax) {
    let rowsHTML = breaks.map((b, idx) => `
        <div class="cls-row" data-idx="${idx}">
            <span class="cls-row-label">${idx + 1}</span>
            <input type="number" step="any" class="cls-min" value="${b.min}" title="ค่าต่ำสุดของช่วง">
            <span>ถึง</span>
            <input type="number" step="any" class="cls-max" value="${b.max}" title="ค่าสูงสุดของช่วง">
            <span>=</span>
            <select class="cls-score" title="คะแนนของช่วงนี้">
                <!-- แก้ไขจาก [1,2,3,4,5,6,7,8,9,10] เป็น [1,2,3,4] -->
                ${[1, 2, 3, 4].map(s => `<option value="${s}" ${s === Math.round(b.score) ? "selected" : ""}>${s}</option>`).join("")}
            </select>
            <span>คะแนน</span>
            <button type="button" class="icon-btn remove-btn cls-remove-row" data-idx="${idx}" title="ลบช่วงนี้">✕</button>
        </div>
    `).join("");

    return `
        <p class="cls-hint">
            ค่าดิบของปัจจัย "<b>${factor}</b>" อยู่ในช่วง <b>${rawMin}</b> ถึง <b>${rawMax}</b> —
            กำหนดช่วงค่า (min–max) และให้คะแนน 1-4 ตามความเหมาะสมของแต่ละช่วงเองได้เลย
        </p>
        <div id="clsRows">${rowsHTML}</div>
        <div style="text-align:center; margin: 14px 0;">
            <button type="button" id="clsAddRow" style="width:auto; padding:8px 20px;">+ เพิ่มช่วง</button>
        </div>
        <div style="display:flex; gap:10px; justify-content:center;">
            <button type="button" id="clsSave" style="width:auto; padding:10px 28px;">บันทึกเกณฑ์</button>
            <button type="button" id="clsClose" style="width:auto; padding:10px 28px; background:#d32f2f;">ปิด</button>
        </div>
    `;
}

// อ่านค่าปัจจุบันในตารางกลับมาเป็น array ของ {min, max, score}
function readClassificationFromDOM() {
    const rows = document.querySelectorAll("#clsRows .cls-row");
    const breaks = [];
    rows.forEach(row => {
        const min = parseFloat(row.querySelector(".cls-min").value);
        const max = parseFloat(row.querySelector(".cls-max").value);
        const score = parseFloat(row.querySelector(".cls-score").value);
        if (!isNaN(min) && !isNaN(max) && !isNaN(score)) {
            breaks.push({ min, max, score });
        }
    });
    return breaks;
}
