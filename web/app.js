"use strict";

// ---------------------------------------------------------------------------
// NIMPilot Dashboard 프론트엔드 로직
//
// web/index.html의 버튼 onclick 핸들러와 데이터 로딩/차트/로그를 담당.
// 백엔드 API는 docs/03-api.md 및 app/main.py의 엔드포인트 참조.
// ---------------------------------------------------------------------------

const API_BASE = ""; // 동일 호스트
const POLL_INTERVAL_MS = 5000;

// 상태
let modelsCache = [];
let benchmarksCache = [];
let pollTimer = null;

// ---------------------------------------------------------------------------
// 유틸
// ---------------------------------------------------------------------------

async function apiFetch(path, options = {}) {
    const opts = Object.assign(
        {
            headers: { "Content-Type": "application/json" },
        },
        options
    );
    const res = await fetch(API_BASE + path, opts);
    const text = await res.text();
    let data = null;
    try {
        data = text ? JSON.parse(text) : null;
    } catch (e) {
        data = { raw: text };
    }

    if (!res.ok) {
        const err =
            data && data.error
                ? data.error.message || data.error.code || res.statusText
                : res.statusText;
        throw new Error(err);
    }
    return data;
}

function log(level, message) {
    const container = document.getElementById("logs-container");
    if (!container) return;

    // empty placeholder 제거
    const empty = container.querySelector(".log-empty");
    if (empty) empty.remove();

    const entry = document.createElement("div");
    entry.className = `log-entry log-${level}`;
    const time = new Date().toLocaleTimeString();
    entry.textContent = `[${time}] ${level.toUpperCase()}: ${message}`;
    container.prepend(entry);

    // 최대 100개 유지
    const entries = container.querySelectorAll(".log-entry");
    if (entries.length > 100) {
        entries[entries.length - 1].remove();
    }
}

async function withButton(buttonId, fn, successMsg) {
    const btn = document.getElementById(buttonId);
    const original = btn ? btn.textContent : "";
    if (btn) {
        btn.disabled = true;
        btn.textContent = "Running...";
    }
    try {
        const result = await fn();
        log("info", successMsg + (result ? " " + JSON.stringify(result) : ""));
        return result;
    } catch (e) {
        log("error", e.message || String(e));
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = original;
        }
    }
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function safe(v, fallback = "-") {
    if (v === null || v === undefined || v === "") return fallback;
    return v;
}

// ---------------------------------------------------------------------------
// Actions (onclick 핸들러)
// ---------------------------------------------------------------------------

async function discoverModels() {
    return withButton(
        "btn-discover",
        () => apiFetch("/discover", { method: "POST" }),
        "Discover started"
    );
}

async function runBenchmark() {
    return withButton(
        "btn-benchmark",
        () => apiFetch("/benchmark", { method: "POST", body: "{}" }),
        "Benchmark started"
    );
}

async function generateConfig() {
    return withButton(
        "btn-generate",
        () => apiFetch("/generate-config", { method: "POST" }),
        "Config generated"
    );
}

async function reloadLiteLLM() {
    return withButton(
        "btn-reload",
        () => apiFetch("/api/litellm/reload", { method: "POST" }),
        "LiteLLM reload requested"
    );
}

async function exportConfig() {
    // 기본: JSON 포맷으로 export
    return withButton(
        "btn-export",
        () =>
            apiFetch("/exporters/json", {
                method: "POST",
                body: JSON.stringify({ limit: 10, use_litellm_proxy: false }),
            }),
        "Config exported"
    );
}

async function startLiteLLM() {
    return withButton(
        "btn-start",
        () => apiFetch("/api/litellm/start", { method: "POST" }),
        "LiteLLM start requested"
    );
}

async function stopLiteLLM() {
    return withButton(
        "btn-stop",
        () => apiFetch("/api/litellm/stop", { method: "POST" }),
        "LiteLLM stop requested"
    );
}

async function restartLiteLLM() {
    return withButton(
        "btn-restart",
        () => apiFetch("/api/litellm/restart", { method: "POST" }),
        "LiteLLM restart requested"
    );
}

// 전역 스코프 노출 (onclick에서 접근 가능하도록)
window.discoverModels = discoverModels;
window.runBenchmark = runBenchmark;
window.generateConfig = generateConfig;
window.reloadLiteLLM = reloadLiteLLM;
window.exportConfig = exportConfig;
window.startLiteLLM = startLiteLLM;
window.stopLiteLLM = stopLiteLLM;
window.restartLiteLLM = restartLiteLLM;

// ---------------------------------------------------------------------------
// 데이터 로딩
// ---------------------------------------------------------------------------

async function loadOverview() {
    try {
        const data = await apiFetch("/api/overview");
        setText("model-count", safe(data.model_count));
        setText("litellm-status", safe(data.litellm_status));

        const bc = data.best_coding_model;
        const br = data.best_reasoning_model;
        const fm = data.fastest_model;

        setText(
            "best-coding",
            bc ? safe(bc.model_id || bc.id || bc.name, "-") : "-"
        );
        setText(
            "best-reasoning",
            br ? safe(br.model_id || br.id || br.name, "-") : "-"
        );
        setText(
            "fastest-model",
            fm ? safe(fm.model_id || fm.id || fm.name, "-") : "-"
        );
    } catch (e) {
        log("error", "overview load failed: " + e.message);
    }
}

async function loadModels() {
    try {
        const data = await apiFetch("/api/models");
        const models = (data && data.models) || [];
        modelsCache = models;

        const tbody = document.getElementById("model-table-body");
        if (!tbody) return;

        if (models.length === 0) {
            tbody.innerHTML =
                '<tr><td colspan="5" class="loading">No models found</td></tr>';
            return;
        }

        tbody.innerHTML = models
            .map((m) => {
                const id = safe(m.id);
                const alias = safe(m.alias);
                const ctx = safe(m.context_length);
                const caps = Array.isArray(m.capabilities)
                    ? m.capabilities.join(", ")
                    : safe(m.capabilities);
                const status = safe(m.status);
                return `<tr>
                    <td>${id}</td>
                    <td>${alias}</td>
                    <td>${ctx}</td>
                    <td>${caps}</td>
                    <td>${status}</td>
                </tr>`;
            })
            .join("");
    } catch (e) {
        log("error", "models load failed: " + e.message);
    }
}

async function loadBenchmarks() {
    try {
        const data = await apiFetch("/benchmarks");
        const results = (data && data.benchmarks) || [];
        benchmarksCache = results;
        drawCharts(results);
    } catch (e) {
        log("error", "benchmarks load failed: " + e.message);
    }
}

// ---------------------------------------------------------------------------
// 차트 (Canvas, 외부 라이브러리 미사용)
// ---------------------------------------------------------------------------

function drawCharts(results) {
    drawBarChart(
        "chart-tps",
        results.map((r) => ({
            label: r.model_id || r.id || "",
            value: (r.metrics && r.metrics.tps) || 0,
        })),
        { title: "TPS", color: "#4caf50" }
    );
    drawBarChart(
        "chart-ttft",
        results.map((r) => ({
            label: r.model_id || r.id || "",
            value: (r.metrics && r.metrics.ttft_ms) || 0,
        })),
        { title: "TTFT (ms)", color: "#2196f3" }
    );
}

function drawBarChart(canvasId, items, opts) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width;
    const H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    const padding = { left: 50, right: 20, top: 30, bottom: 60 };
    const plotW = W - padding.left - padding.right;
    const plotH = H - padding.top - padding.bottom;

    // 제목
    ctx.fillStyle = "#333";
    ctx.font = "14px sans-serif";
    ctx.fillText(opts.title || "", padding.left, 20);

    items = items.filter((i) => i.value !== null && i.value !== undefined);
    if (items.length === 0) {
        ctx.fillStyle = "#999";
        ctx.fillText("No data", W / 2 - 30, H / 2);
        return;
    }

    const maxV = Math.max(...items.map((i) => i.value)) || 1;
    const barW = plotW / items.length;

    // 축
    ctx.strokeStyle = "#ccc";
    ctx.beginPath();
    ctx.moveTo(padding.left, padding.top);
    ctx.lineTo(padding.left, padding.top + plotH);
    ctx.lineTo(padding.left + plotW, padding.top + plotH);
    ctx.stroke();

    // 막대
    ctx.fillStyle = opts.color || "#4caf50";
    items.forEach((item, i) => {
        const h = (item.value / maxV) * plotH;
        const x = padding.left + i * barW + 2;
        const y = padding.top + plotH - h;
        ctx.fillRect(x, y, barW - 4, h);

        // 라벨
        ctx.save();
        ctx.translate(x + (barW - 4) / 2, padding.top + plotH + 8);
        ctx.rotate(Math.PI / 6);
        ctx.fillStyle = "#666";
        ctx.font = "10px sans-serif";
        ctx.fillText(truncate(item.label, 20), 0, 0);
        ctx.restore();

        // 값
        ctx.fillStyle = "#333";
        ctx.font = "10px sans-serif";
        ctx.fillText(item.value.toFixed(1), x + 4, y - 4);
    });
}

function truncate(s, n) {
    if (!s) return "";
    return s.length > n ? s.substring(0, n) + "…" : s;
}

// ---------------------------------------------------------------------------
// 폴링
// ---------------------------------------------------------------------------

async function pollOnce() {
    await Promise.all([loadOverview(), loadModels(), loadBenchmarks()]);
}

function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollOnce, POLL_INTERVAL_MS);
}

// ---------------------------------------------------------------------------
// 초기화
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
    log("info", "Dashboard initialized");
    pollOnce();
    startPolling();
});