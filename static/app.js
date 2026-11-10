"use strict";

/* ================================================================
   RNA STOCK — 前端逻辑
   单位: 购入量 nmol; ddH2O/使用量/剩余量 μL; 浓度 μM (= nmol ÷ μL × 1000)
   ================================================================ */

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));

const esc = s => String(s).replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const todayStr = () => {
  const d = new Date();
  const p = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};

const fmtNum = (x, nd = 2) => {
  if (x === null || x === undefined || x === "" || isNaN(Number(x))) return "—";
  let s = Number(x).toFixed(nd);
  if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  return s;
};

/* ---------- API ---------- */
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { /* ignore */ }
  if (!res.ok || !data || data.ok === false) {
    throw new Error((data && data.msg) || `请求失败 (${res.status})`);
  }
  return data;
}
const apiGet = p => api(p);
const apiPost = (p, body) => api(p, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const apiDelete = p => api(p, { method: "DELETE" });
const apiPut = (p, body) => api(p, {
  method: "PUT",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const wrap = fn => async (...a) => {
  try { return await fn(...a); }
  catch (e) { toast(e.message, "err"); return null; }
};

/* ---------- 提示条 ---------- */
function toast(msg, type = "ok") {
  const el = document.createElement("div");
  el.className = `toast ${type === "err" ? "err" : ""}`;
  el.textContent = msg;
  $("#toast-root").appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 260); }, 3000);
}

/* ---------- 弹窗 ---------- */
function pickEntry({ title, columns, rows, emptyHint }) {
  return new Promise(resolve => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal">
        <div class="modal-head"><span>${esc(title)}</span><button class="modal-x">✕</button></div>
        <div class="modal-body"></div>
        <div class="modal-foot">
          <button class="btn ghost" data-cancel>取消</button>
          <button class="btn primary" data-ok disabled>确定</button>
        </div>
      </div>`;
    const body = $(".modal-body", overlay);
    const okBtn = $("[data-ok]", overlay);
    let pickedId = null;
    const done = id => {
      const row = rows.find(r => r.id === id);
      overlay.remove();
      resolve(row ? { id, seq: row.seq } : null);
    };

    if (!rows.length) {
      body.innerHTML = `<div class="empty">${esc(emptyHint || "暂无条目")}</div>`;
    } else {
      const table = document.createElement("table");
      table.className = "table pick";
      table.innerHTML =
        "<thead><tr>" +
        columns.map(c => `<th class="${c.align || ""}">${esc(c.label)}</th>`).join("") +
        "</tr></thead><tbody>" +
        rows.map(r =>
          `<tr data-id="${r.id}">` +
          columns.map(c => `<td class="${c.align || ""}">${r[c.key]}</td>`).join("") +
          "</tr>"
        ).join("") +
        "</tbody>";
      body.appendChild(table);
      $$("tbody tr", table).forEach(tr => {
        tr.addEventListener("click", () => {
          $$("tbody tr", table).forEach(x => x.classList.remove("sel"));
          tr.classList.add("sel");
          pickedId = Number(tr.dataset.id);
          okBtn.disabled = false;
        });
        tr.addEventListener("dblclick", () => done(Number(tr.dataset.id)));
      });
    }
    okBtn.addEventListener("click", () => done(pickedId));
    $("[data-cancel]", overlay).addEventListener("click", () => done(null));
    $(".modal-x", overlay).addEventListener("click", () => done(null));
    overlay.addEventListener("click", e => { if (e.target === overlay) done(null); });
    document.body.appendChild(overlay);
  });
}

function confirmDialog(msgHtml) {
  return new Promise(resolve => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal" style="width:min(420px,92vw)">
        <div class="modal-head"><span>确认操作</span><button class="modal-x">✕</button></div>
        <div class="modal-body"><div class="modal-msg">${msgHtml}</div></div>
        <div class="modal-foot">
          <button class="btn ghost" data-no>取消</button>
          <button class="btn danger" data-yes>确认删除</button>
        </div>
      </div>`;
    const done = v => { overlay.remove(); resolve(v); };
    $("[data-yes]", overlay).addEventListener("click", () => done(true));
    $("[data-no]", overlay).addEventListener("click", () => done(false));
    $(".modal-x", overlay).addEventListener("click", () => done(false));
    overlay.addEventListener("click", e => { if (e.target === overlay) done(false); });
    document.body.appendChild(overlay);
  });
}

/* ---------- 表单弹窗 (编辑 / 新增) ---------- */
function openFormModal({ title, fields, initial }) {
  return new Promise(resolve => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal">
        <div class="modal-head"><span>${esc(title)}</span><button class="modal-x">✕</button></div>
        <div class="modal-body"></div>
        <div class="modal-foot">
          <button class="btn ghost" data-cancel>取消</button>
          <button class="btn primary" data-ok>保存</button>
        </div>
      </div>`;
    const body = $(".modal-body", overlay);
    const form = document.createElement("div");
    form.className = "form";
    const inputs = {};
    fields.forEach(f => {
      const div = document.createElement("div");
      div.className = "field";
      const label = document.createElement("label");
      label.textContent = f.label;
      if (f.unit) {
        const u = document.createElement("span");
        u.className = "unit";
        u.textContent = f.unit;
        label.appendChild(u);
      }
      const inp = document.createElement("input");
      inp.type = f.type || "text";
      if (inp.type === "number") {
        inp.step = "any";
        inp.min = f.min !== undefined ? f.min : 0;
        inp.classList.add("num");
      }
      inp.placeholder = f.placeholder || "";
      const initVal = initial && initial[f.key] !== undefined && initial[f.key] !== null
        ? initial[f.key] : (f.value || "");
      inp.value = initVal;
      div.appendChild(label);
      div.appendChild(inp);
      form.appendChild(div);
      inputs[f.key] = inp;
    });
    body.appendChild(form);
    /* 自动计算字段(如浓度 = 购入量 ÷ ddH2O 量 × 1000) */
    fields.forEach(f => {
      if (f.autoFrom && f.autoCalc) {
        const recompute = () => {
          const vals = f.autoFrom.map(k => parseFloat(inputs[k].value));
          if (vals.every(v => !isNaN(v) && v > 0)) {
            inputs[f.key].value = fmtNum(f.autoCalc(...vals), 4);
          }
        };
        f.autoFrom.forEach(k => inputs[k].addEventListener("input", recompute));
      }
    });
    const done = v => { overlay.remove(); resolve(v); };
    $("[data-ok]", overlay).addEventListener("click", () => {
      const out = {};
      for (const f of fields) {
        const raw = inputs[f.key].value.trim();
        if (f.required && raw === "") {
          toast(`${f.label} 不能为空`, "err");
          inputs[f.key].focus();
          return;
        }
        out[f.key] = f.type === "number" ? parseFloat(raw) : raw;
      }
      done(out);
    });
    $("[data-cancel]", overlay).addEventListener("click", () => done(null));
    $(".modal-x", overlay).addEventListener("click", () => done(null));
    overlay.addEventListener("click", e => { if (e.target === overlay) done(null); });
    document.body.appendChild(overlay);
  });
}

/* ---------- 状态 ---------- */
const state = {
  view: "purchase",
  mode: "prepare",
  powderId: null,
  solutionId: null,
  whTab: "powder",
  lastPowders: [],
  lastSolutions: [],
};

/* ---------- 视图切换 ---------- */
function switchView(v) {
  state.view = v;
  $$(".mode-btn").forEach(b => b.classList.toggle("active", b.dataset.view === v));
  $$(".view").forEach(sec => {
    const on = sec.dataset.view === v;
    sec.classList.toggle("active", on);
    if (on) {
      sec.classList.remove("anim");
      void sec.offsetWidth;
      sec.classList.add("anim");
    }
  });
  if (v === "warehouse") wrap(loadWarehouse)();
}

function setMode(m) {
  state.mode = m;
  $$(".seg-btn").forEach(b => b.classList.toggle("active", b.dataset.mode === m));
  $("#form-prepare").classList.toggle("hidden", m !== "prepare");
  $("#form-use").classList.toggle("hidden", m !== "use");
}

function switchWhTab(t) {
  state.whTab = t;
  $("#tab-powder").classList.toggle("active", t === "powder");
  $("#tab-solution").classList.toggle("active", t === "solution");
  $("#table-powder").classList.toggle("hidden", t !== "powder");
  $("#table-solution").classList.toggle("hidden", t !== "solution");
}

/* ---------- LCD 读数 ---------- */
function setLcd(lcdSel, valSel, formulaSel, { val, formula, state: st }) {
  const lcd = $(lcdSel);
  $(valSel).textContent = val;
  $(formulaSel).textContent = formula;
  lcd.classList.toggle("err", st === "err");
  if (st === "ok" && val !== "—") {
    lcd.classList.remove("flash");
    void lcd.offsetWidth;
    lcd.classList.add("flash");
  }
}

function calcConc() {
  const amt = parseFloat($("#pp-amount").value);
  const water = parseFloat($("#pp-water").value);
  if (isNaN(amt)) return setLcd("#lcd-conc", "#conc-val", "#conc-formula",
    { val: "—", formula: "请先选择干粉条目", state: "idle" });
  if (isNaN(water)) return setLcd("#lcd-conc", "#conc-val", "#conc-formula",
    { val: "—", formula: "浓度 = 购入量 ÷ ddH2O 量", state: "idle" });
  if (water <= 0) return setLcd("#lcd-conc", "#conc-val", "#conc-formula",
    { val: "—", formula: "ddH2O 量需大于 0", state: "err" });
  setLcd("#lcd-conc", "#conc-val", "#conc-formula", {
    val: fmtNum(amt / water * 1000, 4),
    formula: `${fmtNum(amt)} nmol ÷ ${fmtNum(water)} μL × 1000`,
    state: "ok",
  });
}

function calcRemain() {
  const remain = parseFloat($("#up-remain").value);
  const usage = parseFloat($("#up-usage").value);
  if (isNaN(remain)) return setLcd("#lcd-remain", "#remain-val", "#remain-formula",
    { val: "—", formula: "请先选择溶液条目", state: "idle" });
  if (isNaN(usage)) return setLcd("#lcd-remain", "#remain-val", "#remain-formula",
    { val: "—", formula: "剩余量 = 当前剩余量 − 使用量", state: "idle" });
  if (usage <= 0) return setLcd("#lcd-remain", "#remain-val", "#remain-formula",
    { val: "—", formula: "使用量需大于 0", state: "err" });
  if (usage > remain) return setLcd("#lcd-remain", "#remain-val", "#remain-formula",
    { val: "—", formula: `使用量超过当前剩余量 (${fmtNum(remain)} μL)`, state: "err" });
  setLcd("#lcd-remain", "#remain-val", "#remain-formula", {
    val: fmtNum(remain - usage),
    formula: `${fmtNum(remain)} μL − ${fmtNum(usage)} μL`,
    state: "ok",
  });
}

/* ---------- 表单重置 ---------- */
function resetPrepare() {
  state.powderId = null;
  ["pp-name", "pp-date", "pp-amount", "pp-water"].forEach(id => { $("#" + id).value = ""; });
  $("#pp-prepdate").value = todayStr();
  $("#sel-powder").textContent = "尚未选择";
  $("#sel-powder").classList.remove("has");
  setLcd("#lcd-conc", "#conc-val", "#conc-formula",
    { val: "—", formula: "请先选择干粉条目", state: "idle" });
}

function resetUse() {
  state.solutionId = null;
  ["up-name", "up-date", "up-amount", "up-pdate", "up-conc", "up-remain", "up-usage"].forEach(id => { $("#" + id).value = ""; });
  $("#sel-solution").textContent = "尚未选择";
  $("#sel-solution").classList.remove("has");
  setLcd("#lcd-remain", "#remain-val", "#remain-formula",
    { val: "—", formula: "请先选择溶液条目", state: "idle" });
}

/* ---------- 仓库 ---------- */
const POWDER_COLS = [
  { key: "seq", label: "编号" },
  { key: "rna_name", label: "RNA 种类" },
  { key: "purchase_date", label: "购入日期" },
  { key: "amount", label: "购入量 (nmol)", align: "num" },
];
const SOLUTION_COLS = [
  { key: "seq", label: "编号" },
  { key: "rna_name", label: "RNA 种类" },
  { key: "purchase_date", label: "购入日期" },
  { key: "amount", label: "购入量 (nmol)", align: "num" },
  { key: "prep_date", label: "配制日期" },
  { key: "water_vol", label: "ddH2O 量 (μL)", align: "num" },
  { key: "concentration", label: "配制浓度 (μM)", align: "num" },
  { key: "remaining", label: "剩余量 (μL)", align: "num" },
];

const SOLUTION_FIELDS = [
  { key: "rna_name", label: "RNA 种类", type: "text", required: true },
  { key: "purchase_date", label: "购入日期", type: "date", required: true },
  { key: "amount", label: "购入量", unit: "nmol", type: "number", required: true },
  { key: "prep_date", label: "配制日期", type: "date", required: true },
  { key: "water_vol", label: "ddH2O 量", unit: "μL", type: "number", required: true },
  { key: "concentration", label: "配制浓度", unit: "μM", type: "number", required: true,
    autoFrom: ["amount", "water_vol"], autoCalc: (a, w) => a / w * 1000 },
  { key: "remaining", label: "剩余量", unit: "μL", type: "number", required: true },
];

function renderTable(el, columns, rows, kind) {
  if (!rows.length) {
    el.innerHTML = `<div class="empty">暂无${kind === "powder" ? "干粉" : "溶液"}条目 — 请先${kind === "powder" ? "「购入」登记" : "「配制」生成或点右上角「添加溶液」"}</div>`;
    return;
  }
  el.innerHTML =
    `<table class="table"><thead><tr>` +
    columns.map(c => `<th class="${c.align || ""}">${esc(c.label)}</th>`).join("") +
    `<th>操作</th></tr></thead><tbody>` +
    rows.map(r =>
      `<tr>` +
      columns.map(c => `<td class="${c.align || ""}">${r[c.key]}</td>`).join("") +
      `<td><button class="op-btn" data-edit data-kind="${kind}" data-id="${r.id}">编辑</button>` +
      `<button class="op-btn" data-copy data-kind="${kind}" data-id="${r.id}">复制</button>` +
      `<button class="op-btn del" data-del data-kind="${kind}" data-id="${r.id}">删除</button></td></tr>`
    ).join("") +
    `</tbody></table>`;
}

const fmtPowder = (x, i) => ({
  seq: i + 1, id: x.id, rna_name: esc(x.rna_name), purchase_date: esc(x.purchase_date),
  amount: fmtNum(x.amount),
});
const fmtSolution = (x, i) => ({
  seq: i + 1, id: x.id, rna_name: esc(x.rna_name), purchase_date: esc(x.purchase_date),
  amount: fmtNum(x.amount), prep_date: esc(x.prep_date),
  water_vol: fmtNum(x.water_vol), concentration: fmtNum(x.concentration, 4),
  remaining: fmtNum(x.remaining),
});

async function loadWarehouse() {
  const [p, s] = await Promise.all([apiGet("/api/powders"), apiGet("/api/solutions")]);
  state.lastPowders = p.powders;
  state.lastSolutions = s.solutions;
  renderTable($("#table-powder"), POWDER_COLS, p.powders.map((x, i) => fmtPowder(x, i)), "powder");
  renderTable($("#table-solution"), SOLUTION_COLS, s.solutions.map((x, i) => fmtSolution(x, i)), "solution");
  $("#cnt-powder").textContent = p.powders.length;
  $("#cnt-solution").textContent = s.solutions.length;
}

/* ---------- 仓库行操作: 编辑 / 复制 / 删除 / 添加溶液 ---------- */

async function handleEdit(kind, id) {
  if (kind === "powder") {
    const idx = state.lastPowders.findIndex(x => x.id === id);
    if (idx < 0) return toast("条目已不存在", "err");
    const p = state.lastPowders[idx];
    const v = await openFormModal({
      title: `编辑干粉条目 #${idx + 1}`,
      fields: [
        { key: "rna_name", label: "RNA 种类", type: "text", required: true },
        { key: "purchase_date", label: "购入日期", type: "date", required: true },
        { key: "amount", label: "购入量", unit: "nmol", type: "number", required: true },
      ],
      initial: p,
    });
    if (!v) return;
    const r = await apiPut(`/api/powders/${id}`, v);
    toast(r.msg);
  } else {
    const idx = state.lastSolutions.findIndex(x => x.id === id);
    if (idx < 0) return toast("条目已不存在", "err");
    const s = state.lastSolutions[idx];
    const v = await openFormModal({
      title: `编辑溶液条目 #${idx + 1}`,
      fields: SOLUTION_FIELDS,
      initial: s,
    });
    if (!v) return;
    const r = await apiPut(`/api/solutions/${id}`, v);
    toast(r.msg);
  }
  await loadWarehouse();
}

async function handleCopy(kind, id) {
  if (kind === "powder") {
    const p = state.lastPowders.find(x => x.id === id);
    if (!p) return toast("条目已不存在", "err");
    const r = await apiPost("/api/powders",
      { rna_name: p.rna_name, purchase_date: p.purchase_date, amount: p.amount });
    toast(r.msg);
  } else {
    const s = state.lastSolutions.find(x => x.id === id);
    if (!s) return toast("条目已不存在", "err");
    const r = await apiPost("/api/solutions", {
      rna_name: s.rna_name, purchase_date: s.purchase_date, amount: s.amount,
      prep_date: s.prep_date, water_vol: s.water_vol,
      concentration: s.concentration, remaining: s.remaining,
    });
    toast(r.msg);
  }
  await loadWarehouse();
}

async function handleDelete(kind, id) {
  const label = kind === "powder" ? "干粉" : "溶液";
  const arr = kind === "powder" ? state.lastPowders : state.lastSolutions;
  const idx = arr.findIndex(x => x.id === id);
  const seq = idx >= 0 ? idx + 1 : "";
  const yes = await confirmDialog(`确定删除该<b>${label}条目 #${seq}</b> 吗?<br>删除后不可恢复。`);
  if (!yes) return;
  const r = await apiDelete(`/api/${kind === "powder" ? "powders" : "solutions"}/${id}`);
  toast(r.msg);
  await loadWarehouse();
}

async function handleAddSolution() {
  const v = await openFormModal({
    title: "添加溶液条目 (已有库存)",
    fields: SOLUTION_FIELDS,
    initial: { purchase_date: todayStr(), prep_date: todayStr() },
  });
  if (!v) return;
  const r = await apiPost("/api/solutions", v);
  toast(r.msg);
  await loadWarehouse();
}

/* ---------- 事件绑定 ---------- */
function init() {
  $("#p-date").value = todayStr();
  $("#pp-prepdate").value = todayStr();

  $$(".mode-btn").forEach(b => b.addEventListener("click", () => switchView(b.dataset.view)));
  $$(".seg-btn").forEach(b => b.addEventListener("click", () => setMode(b.dataset.mode)));
  $("#tab-powder").addEventListener("click", () => switchWhTab("powder"));
  $("#tab-solution").addEventListener("click", () => switchWhTab("solution"));

  /* 购入 */
  $("#btn-purchase").addEventListener("click", () => wrap(async () => {
    const rna_name = $("#p-name").value.trim();
    const purchase_date = $("#p-date").value;
    const amount = parseFloat($("#p-amount").value);
    if (!rna_name) return toast("请输入 RNA 种类", "err");
    if (!purchase_date) return toast("请输入购入日期", "err");
    if (!(amount > 0)) return toast("购入量必须是大于 0 的数字", "err");
    const r = await apiPost("/api/powders", { rna_name, purchase_date, amount });
    toast(r.msg);
    $("#p-name").value = "";
    $("#p-amount").value = "";
    $("#p-date").value = todayStr();
  })());

  /* 配制 */
  $("#btn-pick-powder").addEventListener("click", () => wrap(async () => {
    const r = await apiGet("/api/powders");
    if (!r.powders.length) return toast("仓库中没有干粉条目, 请先「购入」", "err");
    const res = await pickEntry({
      title: "选择干粉条目",
      columns: [
        { key: "seq", label: "编号" },
        { key: "rna_name", label: "RNA 种类" },
        { key: "purchase_date", label: "购入日期" },
        { key: "amount", label: "购入量 (nmol)", align: "num" },
      ],
      rows: r.powders.map((p, i) => ({
        id: p.id, seq: i + 1, rna_name: esc(p.rna_name), purchase_date: esc(p.purchase_date), amount: fmtNum(p.amount),
      })),
      emptyHint: "暂无干粉条目",
    });
    if (!res) return;
    const p = r.powders.find(x => x.id === res.id);
    if (!p) return toast("条目已不存在", "err");
    state.powderId = p.id;
    $("#sel-powder").textContent = `#${res.seq} · ${p.rna_name} · ${p.purchase_date}`;
    $("#sel-powder").classList.add("has");
    $("#pp-name").value = p.rna_name;
    $("#pp-date").value = p.purchase_date;
    $("#pp-amount").value = p.amount;
    calcConc();
  })());

  $("#pp-water").addEventListener("input", calcConc);

  $("#btn-prepare").addEventListener("click", () => wrap(async () => {
    if (!state.powderId) return toast("请先选择干粉条目", "err");
    const prep_date = $("#pp-prepdate").value;
    const water_vol = parseFloat($("#pp-water").value);
    if (!prep_date) return toast("请输入配制日期", "err");
    if (!(water_vol > 0)) return toast("ddH2O 量必须是大于 0 的数字", "err");
    const r = await apiPost("/api/prepare", { powder_id: state.powderId, prep_date, water_vol });
    toast(r.msg);
    resetPrepare();
  })());

  /* 使用 */
  $("#btn-pick-solution").addEventListener("click", () => wrap(async () => {
    const r = await apiGet("/api/solutions");
    if (!r.solutions.length) return toast("仓库中没有溶液条目, 请先「配制」", "err");
    const res = await pickEntry({
      title: "选择溶液条目",
      columns: [
        { key: "seq", label: "编号" },
        { key: "rna_name", label: "RNA 种类" },
        { key: "purchase_date", label: "购入日期" },
        { key: "prep_date", label: "配制日期" },
        { key: "concentration", label: "浓度 (μM)", align: "num" },
        { key: "remaining", label: "剩余量 (μL)", align: "num" },
      ],
      rows: r.solutions.map((s, i) => ({
        id: s.id, seq: i + 1, rna_name: esc(s.rna_name), purchase_date: esc(s.purchase_date),
        prep_date: esc(s.prep_date), concentration: fmtNum(s.concentration, 4), remaining: fmtNum(s.remaining),
      })),
      emptyHint: "暂无溶液条目",
    });
    if (!res) return;
    const s = r.solutions.find(x => x.id === res.id);
    if (!s) return toast("条目已不存在", "err");
    state.solutionId = s.id;
    $("#sel-solution").textContent = `#${res.seq} · ${s.rna_name}`;
    $("#sel-solution").classList.add("has");
    $("#up-name").value = s.rna_name;
    $("#up-date").value = s.purchase_date;
    $("#up-amount").value = s.amount;
    $("#up-pdate").value = s.prep_date;
    $("#up-conc").value = s.concentration;
    $("#up-remain").value = s.remaining;
    calcRemain();
  })());

  $("#up-usage").addEventListener("input", calcRemain);

  $("#btn-use").addEventListener("click", () => wrap(async () => {
    if (!state.solutionId) return toast("请先选择溶液条目", "err");
    const usage = parseFloat($("#up-usage").value);
    if (!(usage > 0)) return toast("使用量必须是大于 0 的数字", "err");
    const r = await apiPost("/api/use", { solution_id: state.solutionId, usage });
    toast(r.msg);
    resetUse();
  })());

  /* 仓库行操作(编辑/复制/删除) + 刷新 + 添加溶液 */
  document.addEventListener("click", e => {
    const t = e.target.closest("[data-del],[data-edit],[data-copy]");
    if (!t) return;
    const { kind } = t.dataset;
    const id = Number(t.dataset.id);
    if (t.hasAttribute("data-del")) wrap(() => handleDelete(kind, id))();
    else if (t.hasAttribute("data-edit")) wrap(() => handleEdit(kind, id))();
    else wrap(() => handleCopy(kind, id))();
  });
  $("#btn-wh-refresh").addEventListener("click", () => wrap(loadWarehouse)());
  $("#btn-add-solution").addEventListener("click", () => wrap(handleAddSolution)());

  switchView("purchase");
}

document.addEventListener("DOMContentLoaded", init);
