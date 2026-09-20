// MT4-style terminal front-end

// ---------- State ----------
const state = {
    signals: [],
    selectedPair: null,
    interval: '1h',
    currentChartData: null
};

// ---------- DOM ----------
const mwBody = document.getElementById('mwBody');
const posBody = document.getElementById('posBody');
const histBody = document.getElementById('histBody');
const signalDetail = document.getElementById('signalDetail');
const chartSymbol = document.getElementById('chartSymbol');
const chartTF = document.getElementById('chartTF');
const chartCanvas = document.getElementById('priceChart');
const chartLoading = document.getElementById('chartLoading');
const chartInfo = document.getElementById('chartInfo');
const marketStatus = document.getElementById('marketStatus');
const accountSummary = document.getElementById('accountSummary');
const symbolSearch = document.getElementById('symbolSearch');

// ---------- Clock ----------
function updateClock() {
    const now = new Date();
    const time = now.toTimeString().slice(0, 8);
    document.getElementById('mtClock').textContent = time;
    document.getElementById('mtDate').textContent = now.toISOString().slice(0, 10).replace(/-/g, '.');
}
setInterval(updateClock, 1000);
updateClock();

// ---------- Tabs ----------
document.querySelectorAll('.mt-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.mt-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.mt-tab-content').forEach(c => c.classList.add('hidden'));
        tab.classList.add('active');
        document.getElementById('tab-' + tab.dataset.tab).classList.remove('hidden');
        if (tab.dataset.tab === 'history') loadHistory();
    });
});

// ---------- Timeframe buttons ----------
document.querySelectorAll('.mt-tf-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.mt-tf-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.interval = btn.dataset.tf.toLowerCase();
        chartTF.textContent = btn.dataset.tf;
        fetchSignals();
        if (state.selectedPair) selectPair(state.selectedPair);
    });
});

// ---------- Signal fetching ----------
async function fetchSignals() {
    try {
        const resp = await fetch('/api/signals', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pairs: 'EURUSD=X,GBPUSD=X,AUDUSD=X,USDCAD=X,USDCHF=X,EURGBP=X,EURJPY=X,NZDUSD=X,GBPJPY=X,USDJPY=X',
                interval: state.interval,
                atr_period: 14,
                risk_mult: 1.0
            })
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        state.signals = await resp.json();
        renderMarketWatch();
        renderAccountSummary();
    } catch (err) {
        console.error(err);
        mwBody.innerHTML = `<tr><td colspan="5" class="mt-empty">Failed to fetch: ${err.message}</td></tr>`;
    }
}

// ---------- Market watch ----------
function renderMarketWatch() {
    if (!state.signals || state.signals.length === 0) {
        mwBody.innerHTML = `<tr><td colspan="5" class="mt-empty">No signals</td></tr>`;
        return;
    }
    const q = (symbolSearch.value || '').toUpperCase();
    const filtered = state.signals.filter(s => !q || s.pair.includes(q));
    mwBody.innerHTML = '';
    filtered.forEach(sig => {
        const tr = document.createElement('tr');
        if (state.selectedPair === sig.pair) tr.classList.add('selected');
        tr.dataset.pair = sig.pair;
        const sigClass = sig.signal === 'BUY' ? 'sig-buy' :
            sig.signal === 'SELL' ? 'sig-sell' : 'sig-hold';
        tr.innerHTML = `
            <td>${sig.pair}</td>
            <td class="num bid">${sig.price ? sig.price.toFixed(5) : '—'}</td>
            <td class="num ask">${sig.price ? (sig.price + 0.0001).toFixed(5) : '—'}</td>
            <td class="num ${sigClass}">${sig.signal || 'HOLD'}</td>
            <td class="num">${sig.confidence ? (sig.confidence * 100).toFixed(0) + '%' : '—'}</td>
        `;
        tr.addEventListener('click', () => selectPair(sig.pair));
        mwBody.appendChild(tr);
    });
}

symbolSearch.addEventListener('input', renderMarketWatch);

// ---------- Select pair ----------
async function selectPair(pair) {
    state.selectedPair = pair;
    const sig = state.signals.find(s => s.pair === pair);
    if (!sig) return;

    chartSymbol.textContent = pair;
    renderSignalDetail(sig);
    renderMarketWatch();

    // Update market status (basic heuristic based on signal time)
    const now = new Date();
    const day = now.getUTCDay();
    const hour = now.getUTCHours();
    if (day === 0 || day === 6 || hour < 21 || hour >= 22) {
        marketStatus.textContent = 'Market closed';
        marketStatus.classList.add('closed');
    } else {
        marketStatus.textContent = 'Market open';
        marketStatus.classList.remove('closed');
    }

    await renderChart(sig);
}

// ---------- Signal detail ----------
function renderSignalDetail(sig) {
    const conf = sig.confidence ? (sig.confidence * 100).toFixed(1) + '%' : '0%';
    const readyText = sig.trade_ready ? 'Ready' : (sig.trade_ready_reason || 'Not ready');
    signalDetail.innerHTML = `
        <div class="row"><span class="label">Symbol</span><span class="value">${sig.pair}</span></div>
        <div class="row"><span class="label">Signal</span><span class="value"><span class="sig-badge ${sig.signal}">${sig.signal}</span></span></div>
        <div class="row"><span class="label">Confidence</span><span class="value">${conf}</span></div>
        <div class="row"><span class="label">Price</span><span class="value">${sig.price ? sig.price.toFixed(5) : '—'}</span></div>
        <div class="row"><span class="label">Stop Loss</span><span class="value">${sig.sl ? sig.sl.toFixed(5) : '—'}</span></div>
        <div class="row"><span class="label">Take Profit</span><span class="value">${sig.tp ? sig.tp.toFixed(5) : '—'}</span></div>
        <div class="row"><span class="label">ATR</span><span class="value">${sig.atr ? sig.atr.toFixed(5) : '—'}</span></div>
        <div class="row"><span class="label">Model</span><span class="value">${sig.model_used || '—'}</span></div>
        <div class="row"><span class="label">Trade Ready</span><span class="value">${readyText}</span></div>
        <div class="mt-trade-actions">
            <button class="mt-trade-btn buy" id="btnBuy" ${sig.signal !== 'BUY' ? 'disabled' : ''}>
                <i class="fas fa-arrow-up"></i> BUY ${sig.price ? sig.price.toFixed(5) : ''}
            </button>
            <button class="mt-trade-btn sell" id="btnSell" ${sig.signal !== 'SELL' ? 'disabled' : ''}>
                <i class="fas fa-arrow-down"></i> SELL ${sig.price ? sig.price.toFixed(5) : ''}
            </button>
        </div>
    `;
    const buyBtn = document.getElementById('btnBuy');
    const sellBtn = document.getElementById('btnSell');
    if (buyBtn) buyBtn.addEventListener('click', () => executeTrade(sig));
    if (sellBtn) sellBtn.addEventListener('click', () => executeTrade(sig));
}

// ---------- Chart (candlestick + signal) ----------
async function renderChart(sig) {
    if (!sig.chart || !sig.chart.dates || sig.chart.dates.length === 0) {
        chartLoading.textContent = 'No chart data';
        chartLoading.style.display = 'block';
        return;
    }
    chartLoading.style.display = 'none';

    const dates = sig.chart.dates;
    const prices = sig.chart.prices;
    const ctx = chartCanvas.getContext('2d');

    // Resize canvas to container
    const container = chartCanvas.parentElement;
    const dpr = window.devicePixelRatio || 1;
    const w = container.clientWidth;
    const h = container.clientHeight;
    chartCanvas.width = w * dpr;
    chartCanvas.height = h * dpr;
    chartCanvas.style.width = w + 'px';
    chartCanvas.style.height = h + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const padding = { top: 20, right: 70, bottom: 30, left: 10 };
    const plotW = w - padding.left - padding.right;
    const plotH = h - padding.top - padding.bottom;

    // Compute price range
    let minP = Math.min(...prices);
    let maxP = Math.max(...prices);
    const pad = (maxP - minP) * 0.08 || 0.001;
    minP -= pad;
    maxP += pad;

    // Background
    ctx.fillStyle = '#0f0f0f';
    ctx.fillRect(0, 0, w, h);

    // Grid
    ctx.strokeStyle = '#1a1a1a';
    ctx.lineWidth = 1;
    const gridLines = 6;
    for (let i = 0; i <= gridLines; i++) {
        const y = padding.top + (plotH / gridLines) * i;
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(padding.left + plotW, y);
        ctx.stroke();
        // Price labels on right
        const price = maxP - (maxP - minP) * (i / gridLines);
        ctx.fillStyle = '#888';
        ctx.font = '10px Consolas, monospace';
        ctx.textAlign = 'left';
        ctx.fillText(price.toFixed(5), padding.left + plotW + 6, y + 3);
    }

    // Vertical grid (dates)
    const dateSteps = 6;
    ctx.textAlign = 'center';
    for (let i = 0; i <= dateSteps; i++) {
        const x = padding.left + (plotW / dateSteps) * i;
        ctx.strokeStyle = '#1a1a1a';
        ctx.beginPath();
        ctx.moveTo(x, padding.top);
        ctx.lineTo(x, padding.top + plotH);
        ctx.stroke();
        const idx = Math.floor((prices.length - 1) * (i / dateSteps));
        const d = dates[idx] || '';
        const label = d.length >= 10 ? d.slice(5, 10) : d;
        ctx.fillStyle = '#888';
        ctx.font = '10px Consolas, monospace';
        ctx.fillText(label, x, padding.top + plotH + 16);
    }

    // Price line
    ctx.strokeStyle = '#26a69a';
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    prices.forEach((p, i) => {
        const x = padding.left + (plotW * i) / (prices.length - 1);
        const y = padding.top + plotH * (1 - (p - minP) / (maxP - minP));
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Fill under line
    const gradient = ctx.createLinearGradient(0, padding.top, 0, padding.top + plotH);
    gradient.addColorStop(0, 'rgba(38, 166, 154, 0.15)');
    gradient.addColorStop(1, 'rgba(38, 166, 154, 0)');
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.moveTo(padding.left, padding.top + plotH);
    prices.forEach((p, i) => {
        const x = padding.left + (plotW * i) / (prices.length - 1);
        const y = padding.top + plotH * (1 - (p - minP) / (maxP - minP));
        ctx.lineTo(x, y);
    });
    ctx.lineTo(padding.left + plotW, padding.top + plotH);
    ctx.closePath();
    ctx.fill();

    // Last price line (red horizontal)
    const lastPrice = prices[prices.length - 1];
    const lastY = padding.top + plotH * (1 - (lastPrice - minP) / (maxP - minP));
    ctx.strokeStyle = '#ff3333';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(padding.left, lastY);
    ctx.lineTo(padding.left + plotW, lastY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Price tag on right
    ctx.fillStyle = '#ff3333';
    ctx.fillRect(padding.left + plotW + 2, lastY - 8, 62, 16);
    ctx.fillStyle = '#fff';
    ctx.font = 'bold 10px Consolas, monospace';
    ctx.textAlign = 'left';
    ctx.fillText(lastPrice.toFixed(5), padding.left + plotW + 6, lastY + 3);

    // Signal markers (Buy = blue ▲, Sell = red ▼)
    if (sig.chart.signal_point) {
        const sp = sig.chart.signal_point;
        const idx = dates.indexOf(sp.date);
        if (idx >= 0) {
            const x = padding.left + (plotW * idx) / (prices.length - 1);
            const y = padding.top + plotH * (1 - (sp.price - minP) / (maxP - minP));
            if (sp.signal === 'BUY') {
                ctx.fillStyle = '#1e88e5';
                ctx.beginPath();
                ctx.moveTo(x, y + 10);
                ctx.lineTo(x - 7, y + 22);
                ctx.lineTo(x + 7, y + 22);
                ctx.closePath();
                ctx.fill();
            } else if (sp.signal === 'SELL') {
                ctx.fillStyle = '#e53935';
                ctx.beginPath();
                ctx.moveTo(x, y - 10);
                ctx.lineTo(x - 7, y - 22);
                ctx.lineTo(x + 7, y - 22);
                ctx.closePath();
                ctx.fill();
            }
        }
    }

    chartInfo.textContent = `Last: ${lastPrice.toFixed(5)} | Bars: ${prices.length} | Interval: ${chartTF.textContent}`;
}

// ---------- Positions ----------
async function loadPositions() {
    try {
        const resp = await fetch('/api/open_trades');
        const trades = await resp.json();
        renderPositions(trades);
    } catch (err) {
        console.error('loadPositions:', err);
    }
}

function renderPositions(trades) {
    if (!trades || trades.length === 0) {
        posBody.innerHTML = `<tr><td colspan="12" class="mt-empty">You don't have any positions</td></tr>`;
        renderAccountSummary(0, 0, 0);
        return;
    }
    posBody.innerHTML = '';
    let totalPnl = 0;
    trades.forEach(t => {
        totalPnl += t.pnl || 0;
        const tr = document.createElement('tr');
        const profitPct = t.profit_pct || 0;
        if (profitPct >= 70) tr.classList.add('profit-70');
        else if (profitPct >= 50) tr.classList.add('profit-50');
        else if (profitPct >= 30) tr.classList.add('profit-30');

        const pnlClass = t.pnl > 0 ? 'pnl-pos' : t.pnl < 0 ? 'pnl-neg' : 'pnl-zero';
        const typeClass = t.signal === 'BUY' ? 'type-buy' : 'type-sell';
        const time = (t.time || '').replace('T', ' ').slice(0, 19);

        tr.innerHTML = `
            <td class="symbol">${t.pair}</td>
            <td>${t.id}</td>
            <td>${time}</td>
            <td class="${typeClass}">${t.signal}</td>
            <td class="num">${(t.volume || 0.01).toFixed(2)}</td>
            <td class="num">${(t.entry || 0).toFixed(5)}</td>
            <td class="num">${t.sl ? t.sl.toFixed(5) : '—'}</td>
            <td class="num">${t.tp ? t.tp.toFixed(5) : '—'}</td>
            <td class="num">${t.current_price ? t.current_price.toFixed(5) : '—'}</td>
            <td class="num">${profitPct.toFixed(1)}%</td>
            <td class="num ${pnlClass}">${(t.pnl || 0).toFixed(2)}</td>
            <td><button class="mt-close-btn" data-id="${t.id}">Close</button></td>
        `;
        posBody.appendChild(tr);
    });
    document.querySelectorAll('.mt-close-btn').forEach(btn => {
        btn.addEventListener('click', () => closeTrade(btn.dataset.id));
    });
    renderAccountSummary(0, 0, totalPnl, trades.length);
}

function renderAccountSummary(balance, equity, pnl, positions) {
    if (balance === undefined) balance = 100000;
    if (equity === undefined) equity = 100000;
    if (pnl === undefined) pnl = 0;
    if (positions === undefined) positions = 0;
    const eq = 100000 + pnl;
    accountSummary.innerHTML =
        `Balance: ${balance.toFixed(2)} &nbsp; Equity: ${eq.toFixed(2)} &nbsp; ` +
        `Free: ${(eq).toFixed(2)} &nbsp; Positions: ${positions} &nbsp; ` +
        `PnL: <span style="color:${pnl >= 0 ? '#00b300' : '#ff3333'}">${pnl.toFixed(2)} USD</span>`;
}

// ---------- Close trade ----------
async function closeTrade(tradeId) {
    if (!confirm(`Close position #${tradeId}?`)) return;
    try {
        const resp = await fetch('/api/close_trade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ trade_id: tradeId })
        });
        const data = await resp.json();
        if (data.success) {
            loadPositions();
        } else {
            alert('Close failed: ' + data.error);
        }
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

// ---------- Execute trade ----------
async function executeTrade(sig) {
    if (!confirm(`Execute ${sig.signal} on ${sig.pair} at ${sig.price}?`)) return;
    try {
        const resp = await fetch('/api/autotrade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pairs: sig.pair + '=X',
                interval: state.interval,
                atr_period: 14,
                risk_mult: 1.0,
                volume: parseFloat(document.getElementById('cfgVol').value) || 0.10
            })
        });
        const result = await resp.json();
        if (resp.ok && result[0] && result[0].trade && result[0].trade.success) {
            alert(`✅ Trade executed! Ticket: ${result[0].trade.order_id}`);
            loadPositions();
        } else {
            const err = (result[0] && result[0].trade && result[0].trade.error) || 'Unknown error';
            alert('❌ Trade failed: ' + err);
        }
    } catch (err) {
        alert('Error executing trade: ' + err.message);
    }
}

// ---------- History ----------
async function loadHistory() {
    // Placeholder — can be extended with a history API
    histBody.innerHTML = `<tr><td colspan="8" class="mt-empty">History endpoint not configured</td></tr>`;
}

// ---------- Settings ----------
document.getElementById('cfgApply').addEventListener('click', async() => {
    const status = document.getElementById('cfgStatus');
    status.textContent = 'Saving…';
    try {
        const resp = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                confidence_threshold: parseFloat(document.getElementById('cfgConf').value),
                trade_volume: parseFloat(document.getElementById('cfgVol').value),
                profit_close_pct: parseFloat(document.getElementById('cfgProfitClose').value)
            })
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        status.textContent = 'Applied ✓';
        setTimeout(() => status.textContent = '', 2500);
    } catch (err) {
        status.textContent = 'Error: ' + err.message;
    }
});

document.getElementById('btn-refresh').addEventListener('click', fetchSignals);
document.getElementById('btn-chart-refresh').addEventListener('click', () => {
    if (state.selectedPair) {
        state.selectedPair = null;
        fetchSignals().then(() => {
            const first = state.signals[0];
            if (first) selectPair(first.pair);
        });
    }
});

document.getElementById('btn-settings').addEventListener('click', () => {
    document.querySelector('.mt-tab[data-tab="config"]').click();
});

document.getElementById('btn-retrain').addEventListener('click', async() => {
    if (!confirm('Retrain LightGBM models? This may take a few minutes.')) return;
    try {
        const resp = await fetch('/api/retrain', { method: 'POST' });
        const data = await resp.json();
        alert(data.success ? '✅ Retraining completed' : '❌ Retraining failed');
    } catch (err) {
        alert('Error: ' + err.message);
    }
});

// ---------- Auto-refresh ----------
setInterval(loadPositions, 5000);
setInterval(fetchSignals, 30000);
window.addEventListener('resize', () => {
    if (state.selectedPair) {
        const sig = state.signals.find(s => s.pair === state.selectedPair);
        if (sig) renderChart(sig);
    }
});

// ---------- Bootstrap ----------
fetchSignals().then(() => {
    loadPositions();
    if (state.signals.length > 0) {
        selectPair(state.signals[0].pair);
    }
});