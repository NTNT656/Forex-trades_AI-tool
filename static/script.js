// MT4-style terminal — responsive front-end (parser-safe)

// ---------- State ----------
var state = {
    signals: [],
    selectedPair: null,
    interval: 'h1',
    currentChartData: null,
    drawerOpen: false
};

// ---------- DOM refs ----------
var mwBody = document.getElementById('mwBody');
var posBody = document.getElementById('posBody');
var posCards = document.getElementById('posCards');
var histBody = document.getElementById('histBody');
var histCards = document.getElementById('histCards');
var signalCard = document.getElementById('signalCard');
var chartSymbol = document.getElementById('chartSymbol');
var chartTF = document.getElementById('chartTF');
var chartCanvas = document.getElementById('priceChart');
var chartLoading = document.getElementById('chartLoading');
var marketStatus = document.getElementById('marketStatus');
var accountSummary = document.getElementById('accountSummary');
var symbolSearch = document.getElementById('symbolSearch');
var symbolSearchMobile = document.getElementById('symbolSearchMobile');
var mobileAccount = document.getElementById('mobileAccount');
var marketPanel = document.getElementById('marketPanel');
var overlay = document.getElementById('overlay');
var mobileTitle = document.getElementById('mobileTitle');

// ---------- Clock ----------
function updateClock() {
    var now = new Date();
    var timeEl = document.getElementById('mtClock');
    var dateEl = document.getElementById('mtDate');
    if (timeEl) timeEl.textContent = now.toTimeString().slice(0, 8);
    if (dateEl) dateEl.textContent = now.toISOString().slice(0, 10).split('-').join('.');
}
setInterval(updateClock, 1000);
updateClock();

// ---------- Drawer ----------
function openDrawer() {
    state.drawerOpen = true;
    if (marketPanel) marketPanel.classList.add('open');
    if (overlay) overlay.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeDrawer() {
    state.drawerOpen = false;
    if (marketPanel) marketPanel.classList.remove('open');
    if (overlay) overlay.classList.remove('active');
    document.body.style.overflow = '';
}
var mobileMenuBtn = document.getElementById('mobileMenuBtn');
var closeDrawerBtn = document.getElementById('closeDrawer');
if (mobileMenuBtn) mobileMenuBtn.addEventListener('click', openDrawer);
if (closeDrawerBtn) closeDrawerBtn.addEventListener('click', closeDrawer);
if (overlay) overlay.addEventListener('click', closeDrawer);

// ---------- Tabs ----------
document.querySelectorAll('.mt-tab').forEach(function(tab) {
    tab.addEventListener('click', function() {
        document.querySelectorAll('.mt-tab').forEach(function(t) { t.classList.remove('active'); });
        document.querySelectorAll('.mt-tab-content').forEach(function(c) { c.classList.remove('active'); });
        tab.classList.add('active');
        var target = document.getElementById('tab-' + tab.dataset.tab);
        if (target) target.classList.add('active');
        if (tab.dataset.tab === 'history') loadHistory();
    });
});

// ---------- Timeframe buttons ----------
document.querySelectorAll('.mt-tf-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
        var tf = btn.dataset.tf;
        document.querySelectorAll('.mt-tf-btn').forEach(function(b) {
            if (b.dataset.tf === tf) {
                b.classList.add('active');
            } else {
                b.classList.remove('active');
            }
        });
        state.interval = tf.toLowerCase();
        if (chartTF) chartTF.textContent = tf;
        fetchSignals();
        if (state.selectedPair) {
            var sig = state.signals.find(function(s) { return s.pair === state.selectedPair; });
            if (sig) selectPair(sig.pair, true);
        }
    });
});

// ---------- Fetch signals ----------
function fetchSignals() {
    var body = JSON.stringify({
        pairs: 'EURUSD=X,GBPUSD=X,AUDUSD=X,USDCAD=X,USDCHF=X,EURGBP=X,EURJPY=X,NZDUSD=X,GBPJPY=X,USDJPY=X',
        interval: state.interval,
        atr_period: 14,
        risk_mult: 1.0
    });
    return fetch('/api/signals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body
    }).then(function(resp) {
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.json();
    }).then(function(data) {
        state.signals = data;
        renderMarketWatch();
        updateMobileTitle();
    }).catch(function(err) {
        console.error('fetchSignals:', err);
        if (mwBody) mwBody.innerHTML = '<tr><td colspan="4" class="mt-empty">Failed: ' + err.message + '</td></tr>';
    });
}

function updateMobileTitle() {
    if (!mobileTitle) return;
    var buys = 0,
        sells = 0;
    state.signals.forEach(function(s) {
        if (s.signal === 'BUY') buys++;
        else if (s.signal === 'SELL') sells++;
    });
    if (buys === 0 && sells === 0) {
        mobileTitle.textContent = 'MetaTrader';
    } else {
        mobileTitle.textContent = 'MetaTrader · ' + buys + '▲ ' + sells + '▼';
    }
}

// ---------- Market watch ----------
function renderMarketWatch() {
    if (!mwBody) return;
    if (!state.signals || state.signals.length === 0) {
        mwBody.innerHTML = '<tr><td colspan="4" class="mt-empty">No signals</td></tr>';
        return;
    }
    var q = '';
    if (symbolSearch && symbolSearch.value) q = symbolSearch.value;
    else if (symbolSearchMobile && symbolSearchMobile.value) q = symbolSearchMobile.value;
    q = String(q).toUpperCase();

    var filtered = state.signals.filter(function(s) {
        return !q || s.pair.indexOf(q) !== -1;
    });

    mwBody.innerHTML = '';
    filtered.forEach(function(sig) {
        var tr = document.createElement('tr');
        if (state.selectedPair === sig.pair) tr.classList.add('selected');
        tr.dataset.pair = sig.pair;

        var sigClass = 'sig-hold';
        if (sig.signal === 'BUY') sigClass = 'sig-buy';
        else if (sig.signal === 'SELL') sigClass = 'sig-sell';

        var chg = 0;
        if (sig.chart && sig.chart.prices && sig.chart.prices.length > 1) {
            var first = sig.chart.prices[0];
            var last = sig.chart.prices[sig.chart.prices.length - 1];
            chg = ((last - first) / first) * 100;
        }
        var chgClass = '';
        if (chg > 0) chgClass = 'chg-pos';
        else if (chg < 0) chgClass = 'chg-neg';

        var sigLabel = '';
        if (sig.signal !== 'HOLD') sigLabel = sig.signal;
        var sigColor = '#7a7a7a';
        if (sig.signal === 'BUY') sigColor = '#26a69a';
        else if (sig.signal === 'SELL') sigColor = '#ef5350';

        var chgText = '—';
        if (chg !== 0) {
            chgText = (chg > 0 ? '+' : '') + chg.toFixed(2) + '%';
        }

        tr.innerHTML =
            '<td>' + sig.pair + ' <span style="color:' + sigColor + ';font-weight:700;font-size:10px;margin-left:4px;">' + sigLabel + '</span></td>' +
            '<td class="num bid">' + (sig.price ? sig.price.toFixed(5) : '—') + '</td>' +
            '<td class="num ask">' + (sig.price ? (sig.price + 0.0001).toFixed(5) : '—') + '</td>' +
            '<td class="num ' + chgClass + '">' + chgText + '</td>';

        tr.addEventListener('click', function() {
            selectPair(sig.pair);
            if (window.innerWidth <= 900) closeDrawer();
        });
        mwBody.appendChild(tr);
    });
}

if (symbolSearch) symbolSearch.addEventListener('input', renderMarketWatch);
if (symbolSearchMobile) symbolSearchMobile.addEventListener('input', renderMarketWatch);

// ---------- Select pair ----------
function selectPair(pair, skipFetch) {
    state.selectedPair = pair;
    var sig = state.signals.find(function(s) { return s.pair === pair; });
    if (!sig) return Promise.resolve();

    if (chartSymbol) chartSymbol.textContent = pair;
    renderSignalCard(sig);
    renderMarketWatch();

    var now = new Date();
    var day = now.getUTCDay();
    var hour = now.getUTCHours();
    var closed = false;
    if (day === 6) closed = true;
    else if (day === 0 && hour < 21) closed = true;
    else if (day === 5 && hour >= 21) closed = true;

    if (marketStatus) {
        if (closed) {
            marketStatus.textContent = 'Market closed';
            marketStatus.classList.add('closed');
        } else {
            marketStatus.textContent = 'Market open';
            marketStatus.classList.remove('closed');
        }
    }

    return renderChart(sig);
}

// ---------- Signal card ----------
function renderSignalCard(sig) {
    if (!signalCard) return;
    var conf = '0%';
    if (sig.confidence) conf = (sig.confidence * 100).toFixed(1) + '%';

    var canBuy = false;
    var canSell = false;
    if (sig.signal === 'BUY' && sig.can_trade === true && sig.trade_ready === true) canBuy = true;
    if (sig.signal === 'SELL' && sig.can_trade === true && sig.trade_ready === true) canSell = true;

    signalCard.innerHTML =
        '<div class="row"><span class="label">Symbol</span><span class="value">' + sig.pair + '</span></div>' +
        '<div class="row"><span class="label">Signal</span><span class="value"><span class="sig-badge ' + sig.signal + '">' + sig.signal + '</span></span></div>' +
        '<div class="row"><span class="label">Confidence</span><span class="value">' + conf + '</span></div>' +
        '<div class="row"><span class="label">Price</span><span class="value">' + (sig.price ? sig.price.toFixed(5) : '—') + '</span></div>' +
        '<div class="row"><span class="label">Take Profit</span><span class="value">' + (sig.tp ? sig.tp.toFixed(5) : '—') + '</span></div>' +
        '<div class="row"><span class="label">Stop Loss</span><span class="value">' + (sig.sl ? sig.sl.toFixed(5) : '—') + '</span></div>' +
        '<div class="row"><span class="label">ATR</span><span class="value">' + (sig.atr ? sig.atr.toFixed(5) : '—') + '</span></div>' +
        '<div class="row"><span class="label">Model</span><span class="value">' + (sig.model_used || '—') + '</span></div>' +
        '<div class="mt-trade-actions">' +
        '<button class="mt-trade-btn buy" id="btnBuy"' + (canBuy ? '' : ' disabled') + '><i class="fas fa-arrow-up"></i> BUY</button>' +
        '<button class="mt-trade-btn sell" id="btnSell"' + (canSell ? '' : ' disabled') + '><i class="fas fa-arrow-down"></i> SELL</button>' +
        '</div>';

    var buyBtn = document.getElementById('btnBuy');
    var sellBtn = document.getElementById('btnSell');
    if (buyBtn) buyBtn.addEventListener('click', function() { executeTrade(sig); });
    if (sellBtn) sellBtn.addEventListener('click', function() { executeTrade(sig); });
}

// ---------- Chart ----------
function renderChart(sig) {
    if (!chartCanvas) return Promise.resolve();
    if (!sig.chart || !sig.chart.dates || sig.chart.dates.length === 0) {
        if (chartLoading) {
            chartLoading.textContent = 'No chart data';
            chartLoading.style.display = 'block';
        }
        return Promise.resolve();
    }
    if (chartLoading) chartLoading.style.display = 'none';

    var dates = sig.chart.dates;
    var prices = sig.chart.prices;
    var ctx = chartCanvas.getContext('2d');

    var container = chartCanvas.parentElement;
    var dpr = window.devicePixelRatio || 1;
    var w = container.clientWidth;
    var h = container.clientHeight;
    if (w === 0 || h === 0) return Promise.resolve();

    chartCanvas.width = w * dpr;
    chartCanvas.height = h * dpr;
    chartCanvas.style.width = w + 'px';
    chartCanvas.style.height = h + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    var isMobile = window.innerWidth <= 900;
    var padding;
    if (isMobile) {
        padding = { top: 15, right: 55, bottom: 22, left: 6 };
    } else {
        padding = { top: 20, right: 70, bottom: 30, left: 10 };
    }
    var plotW = w - padding.left - padding.right;
    var plotH = h - padding.top - padding.bottom;

    var minP = Math.min.apply(null, prices);
    var maxP = Math.max.apply(null, prices);
    var pad = (maxP - minP) * 0.08;
    if (pad === 0) pad = 0.001;
    minP -= pad;
    maxP += pad;

    ctx.fillStyle = '#0f0f0f';
    ctx.fillRect(0, 0, w, h);

    // Grid + price labels
    ctx.strokeStyle = '#1a1a1a';
    ctx.lineWidth = 1;
    var gridLines = isMobile ? 4 : 6;
    ctx.font = (isMobile ? '9px' : '10px') + ' Consolas, monospace';
    ctx.textAlign = 'left';
    for (var i = 0; i <= gridLines; i++) {
        var y = padding.top + (plotH / gridLines) * i;
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(padding.left + plotW, y);
        ctx.stroke();
        var price = maxP - (maxP - minP) * (i / gridLines);
        ctx.fillStyle = '#888';
        ctx.fillText(price.toFixed(5), padding.left + plotW + 5, y + 3);
    }

    // Vertical grid (dates)
    var dateSteps = isMobile ? 3 : 6;
    ctx.textAlign = 'center';
    for (var j = 0; j <= dateSteps; j++) {
        var x = padding.left + (plotW / dateSteps) * j;
        ctx.strokeStyle = '#1a1a1a';
        ctx.beginPath();
        ctx.moveTo(x, padding.top);
        ctx.lineTo(x, padding.top + plotH);
        ctx.stroke();
        var idx = Math.floor((prices.length - 1) * (j / dateSteps));
        var d = dates[idx] || '';
        var label = d.length >= 10 ? d.slice(5, 10) : d;
        ctx.fillStyle = '#888';
        ctx.fillText(label, x, padding.top + plotH + 14);
    }

    // Line color
    var lineColor = '#ef5350';
    if (prices[prices.length - 1] >= prices[0]) lineColor = '#26a69a';

    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    for (var k = 0; k < prices.length; k++) {
        var px = padding.left + (plotW * k) / (prices.length - 1);
        var py = padding.top + plotH * (1 - (prices[k] - minP) / (maxP - minP));
        if (k === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
    }
    ctx.stroke();

    // Gradient fill
    var gradTop = 'rgba(239, 83, 80, 0.18)';
    if (lineColor === '#26a69a') gradTop = 'rgba(38, 166, 154, 0.18)';
    var gradient = ctx.createLinearGradient(0, padding.top, 0, padding.top + plotH);
    gradient.addColorStop(0, gradTop);
    gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.moveTo(padding.left, padding.top + plotH);
    for (var m = 0; m < prices.length; m++) {
        var gx = padding.left + (plotW * m) / (prices.length - 1);
        var gy = padding.top + plotH * (1 - (prices[m] - minP) / (maxP - minP));
        ctx.lineTo(gx, gy);
    }
    ctx.lineTo(padding.left + plotW, padding.top + plotH);
    ctx.closePath();
    ctx.fill();

    // Last price line
    var lastPrice = prices[prices.length - 1];
    var lastY = padding.top + plotH * (1 - (lastPrice - minP) / (maxP - minP));
    ctx.strokeStyle = '#ff3333';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(padding.left, lastY);
    ctx.lineTo(padding.left + plotW, lastY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Price tag
    var tagW = isMobile ? 52 : 62;
    var tagH = 16;
    ctx.fillStyle = '#ff3333';
    ctx.fillRect(padding.left + plotW + 2, lastY - tagH / 2, tagW, tagH);
    ctx.fillStyle = '#fff';
    ctx.font = 'bold ' + (isMobile ? '9px' : '10px') + ' Consolas, monospace';
    ctx.textAlign = 'left';
    ctx.fillText(lastPrice.toFixed(5), padding.left + plotW + 5, lastY + 3);

    // Signal marker
    if (sig.chart.signal_point) {
        var sp = sig.chart.signal_point;
        var sigIdx = dates.indexOf(sp.date);
        if (sigIdx >= 0) {
            var sx = padding.left + (plotW * sigIdx) / (prices.length - 1);
            var sy = padding.top + plotH * (1 - (sp.price - minP) / (maxP - minP));
            if (sp.signal === 'BUY') {
                ctx.fillStyle = '#1e88e5';
                ctx.beginPath();
                ctx.moveTo(sx, sy + 8);
                ctx.lineTo(sx - 7, sy + 20);
                ctx.lineTo(sx + 7, sy + 20);
                ctx.closePath();
                ctx.fill();
            } else if (sp.signal === 'SELL') {
                ctx.fillStyle = '#e53935';
                ctx.beginPath();
                ctx.moveTo(sx, sy - 8);
                ctx.lineTo(sx - 7, sy - 20);
                ctx.lineTo(sx + 7, sy - 20);
                ctx.closePath();
                ctx.fill();
            }
        }
    }

    return Promise.resolve();
}

// ---------- Positions ----------
function loadPositions() {
    return fetch('/api/open_trades')
        .then(function(r) { return r.json(); })
        .then(function(trades) {
            renderPositions(trades);
            updateMobileAccount(trades);
        })
        .catch(function(err) { console.error('loadPositions:', err); });
}

function renderPositions(trades) {
    if (posBody) {
        if (!trades || trades.length === 0) {
            posBody.innerHTML = '<tr><td colspan="12" class="mt-empty">You don\'t have any positions</td></tr>';
        } else {
            posBody.innerHTML = '';
            trades.forEach(function(t) {
                var tr = document.createElement('tr');
                var profitPct = t.profit_pct || 0;
                if (profitPct >= 70) tr.classList.add('profit-70');
                else if (profitPct >= 50) tr.classList.add('profit-50');
                else if (profitPct >= 30) tr.classList.add('profit-30');

                var pnlClass = 'pnl-zero';
                if (t.pnl > 0) pnlClass = 'pnl-pos';
                else if (t.pnl < 0) pnlClass = 'pnl-neg';

                var typeClass = 'type-sell';
                if (t.signal === 'BUY') typeClass = 'type-buy';

                var time = (t.time || '').replace('T', ' ').slice(0, 19);

                tr.innerHTML =
                    '<td class="symbol">' + t.pair + '</td>' +
                    '<td>' + t.id + '</td>' +
                    '<td>' + time + '</td>' +
                    '<td class="' + typeClass + '">' + t.signal + '</td>' +
                    '<td class="num">' + (t.volume || 0.01).toFixed(2) + '</td>' +
                    '<td class="num">' + (t.entry || 0).toFixed(5) + '</td>' +
                    '<td class="num">' + (t.sl ? t.sl.toFixed(5) : '—') + '</td>' +
                    '<td class="num">' + (t.tp ? t.tp.toFixed(5) : '—') + '</td>' +
                    '<td class="num">' + (t.current_price ? t.current_price.toFixed(5) : '—') + '</td>' +
                    '<td class="num">' + profitPct.toFixed(1) + '%</td>' +
                    '<td class="num ' + pnlClass + '">' + (t.pnl || 0).toFixed(2) + '</td>' +
                    '<td><button class="mt-close-btn" data-id="' + t.id + '">Close</button></td>';
                posBody.appendChild(tr);
            });
            posBody.querySelectorAll('.mt-close-btn').forEach(function(btn) {
                btn.addEventListener('click', function() { closeTrade(btn.dataset.id); });
            });
        }
    }

    if (posCards) {
        if (!trades || trades.length === 0) {
            posCards.innerHTML = '<div class="mt-empty">You don\'t have any positions</div>';
        } else {
            posCards.innerHTML = '';
            trades.forEach(function(t) {
                var card = document.createElement('div');
                card.className = 'mt-pos-card';
                var profitPct = t.profit_pct || 0;
                if (profitPct >= 70) card.classList.add('profit-70');
                else if (profitPct >= 50) card.classList.add('profit-50');
                else if (profitPct >= 30) card.classList.add('profit-30');

                var pnlClass = 'zero';
                if (t.pnl > 0) pnlClass = 'pos';
                else if (t.pnl < 0) pnlClass = 'neg';

                var typeClass = 'sell';
                if (t.signal === 'BUY') typeClass = 'buy';

                var time = (t.time || '').replace('T', ' ').slice(11, 19);

                card.innerHTML =
                    '<div class="pc-header">' +
                    '<span class="pc-symbol">' + t.pair + '</span>' +
                    '<span class="pc-type ' + typeClass + '">' + t.signal + '</span>' +
                    '</div>' +
                    '<div class="pc-grid">' +
                    '<div class="pc-item"><span class="pc-label">Vol</span><span class="pc-value">' + (t.volume || 0.01).toFixed(2) + '</span></div>' +
                    '<div class="pc-item"><span class="pc-label">Time</span><span class="pc-value">' + time + '</span></div>' +
                    '<div class="pc-item"><span class="pc-label">Entry</span><span class="pc-value">' + (t.entry || 0).toFixed(5) + '</span></div>' +
                    '<div class="pc-item"><span class="pc-label">Current</span><span class="pc-value">' + (t.current_price ? t.current_price.toFixed(5) : '—') + '</span></div>' +
                    '<div class="pc-item"><span class="pc-label">S/L</span><span class="pc-value">' + (t.sl ? t.sl.toFixed(5) : '—') + '</span></div>' +
                    '<div class="pc-item"><span class="pc-label">T/P</span><span class="pc-value">' + (t.tp ? t.tp.toFixed(5) : '—') + '</span></div>' +
                    '</div>' +
                    '<div class="pc-footer">' +
                    '<div>' +
                    '<span class="pc-pnl ' + pnlClass + '">' + ((t.pnl || 0) >= 0 ? '+' : '') + (t.pnl || 0).toFixed(2) + '</span>' +
                    '<span class="pc-pct">' + profitPct.toFixed(1) + '%</span>' +
                    '</div>' +
                    '<button class="pc-close" data-id="' + t.id + '">Close</button>' +
                    '</div>';
                posCards.appendChild(card);
            });
            posCards.querySelectorAll('.pc-close').forEach(function(btn) {
                btn.addEventListener('click', function() { closeTrade(btn.dataset.id); });
            });
        }
    }

    if (accountSummary) {
        var totalPnl = 0;
        (trades || []).forEach(function(t) { totalPnl += (t.pnl || 0); });
        var eq = 100000 + totalPnl;
        var pnlColor = '#ff3333';
        if (totalPnl >= 0) pnlColor = '#00b300';
        accountSummary.innerHTML =
            'Balance: 100000.00 &nbsp; Equity: ' + eq.toFixed(2) + ' &nbsp; ' +
            'Free: ' + eq.toFixed(2) + ' &nbsp; Positions: ' + (trades || []).length + ' &nbsp; ' +
            'PnL: <span style="color:' + pnlColor + '">' + totalPnl.toFixed(2) + ' USD</span>';
    }
}

function updateMobileAccount(trades) {
    if (!mobileAccount) return;
    var totalPnl = 0;
    (trades || []).forEach(function(t) { totalPnl += (t.pnl || 0); });
    var eq = 100000 + totalPnl;
    var eqEl = document.getElementById('mEq');
    var pnlEl = document.getElementById('mPnl');
    var posEl = document.getElementById('mPos');
    if (eqEl) eqEl.textContent = eq.toFixed(2);
    if (pnlEl) {
        pnlEl.textContent = (totalPnl >= 0 ? '+' : '') + totalPnl.toFixed(2);
        var col = '#e8e8e8';
        if (totalPnl > 0) col = '#00b300';
        else if (totalPnl < 0) col = '#ff3333';
        pnlEl.style.color = col;
    }
    if (posEl) posEl.textContent = (trades || []).length;
}

// ---------- Close trade ----------
function closeTrade(tradeId) {
    if (!confirm('Close position #' + tradeId + '?')) return;
    fetch('/api/close_trade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ trade_id: tradeId })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) loadPositions();
            else alert('Close failed: ' + (data.error || 'unknown'));
        })
        .catch(function(err) { alert('Error: ' + err.message); });
}

// ---------- Execute trade ----------
function executeTrade(sig) {
    if (!confirm('Execute ' + sig.signal + ' on ' + sig.pair + ' at ' + sig.price + '?')) return;
    var cfgVol = document.getElementById('cfgVol');
    var vol = 0.10;
    if (cfgVol) vol = parseFloat(cfgVol.value);
    fetch('/api/autotrade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pairs: sig.pair + '=X',
                interval: state.interval,
                atr_period: 14,
                risk_mult: 1.0,
                volume: vol
            })
        })
        .then(function(r) { return r.json(); })
        .then(function(result) {
            if (result && result[0] && result[0].trade && result[0].trade.success) {
                alert('✅ Trade executed! Ticket: ' + result[0].trade.order_id);
                loadPositions();
            } else {
                var err = 'Unknown error';
                if (result && result[0] && result[0].trade) err = result[0].trade.error || err;
                alert('❌ Trade failed: ' + err);
            }
        })
        .catch(function(err) { alert('Error: ' + err.message); });
}

// ---------- History ----------
function loadHistory() {
    if (histBody) histBody.innerHTML = '<tr><td colspan="8" class="mt-empty">History endpoint not configured</td></tr>';
    if (histCards) histCards.innerHTML = '<div class="mt-empty">History endpoint not configured</div>';
}

// ---------- Settings ----------
var cfgApply = document.getElementById('cfgApply');
if (cfgApply) cfgApply.addEventListener('click', function() {
    var status = document.getElementById('cfgStatus');
    if (status) status.textContent = 'Saving…';
    var cfgConf = document.getElementById('cfgConf');
    var cfgVol = document.getElementById('cfgVol');
    var cfgProfitClose = document.getElementById('cfgProfitClose');
    fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                confidence_threshold: parseFloat(cfgConf.value),
                trade_volume: parseFloat(cfgVol.value),
                profit_close_pct: parseFloat(cfgProfitClose.value)
            })
        })
        .then(function(r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            if (status) {
                status.textContent = 'Applied ✓';
                setTimeout(function() { status.textContent = ''; }, 2500);
            }
        })
        .catch(function(err) {
            if (status) status.textContent = 'Error: ' + err.message;
        });
});

// ---------- Top-bar actions ----------
var btnRefresh = document.getElementById('btn-refresh');
var mobileRefreshBtn = document.getElementById('mobileRefreshBtn');
var btnSettings = document.getElementById('btn-settings');
var btnRetrain = document.getElementById('btn-retrain');

if (btnRefresh) btnRefresh.addEventListener('click', fetchSignals);
if (mobileRefreshBtn) mobileRefreshBtn.addEventListener('click', function() {
    fetchSignals();
    loadPositions();
});
if (btnSettings) btnSettings.addEventListener('click', function() {
    var configTab = document.querySelector('.mt-tab[data-tab="config"]');
    if (configTab) configTab.click();
});
if (btnRetrain) btnRetrain.addEventListener('click', function() {
    if (!confirm('Retrain LightGBM models?')) return;
    fetch('/api/retrain', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            alert(data.success ? '✅ Retraining completed' : '❌ Retraining failed');
        })
        .catch(function(err) { alert('Error: ' + err.message); });
});

// ---------- Auto-refresh ----------
setInterval(loadPositions, 5000);
setInterval(fetchSignals, 30000);

// ---------- Resize ----------
var resizeTimer = null;
window.addEventListener('resize', function() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function() {
        if (state.selectedPair) {
            var sig = state.signals.find(function(s) { return s.pair === state.selectedPair; });
            if (sig) renderChart(sig);
        }
        if (window.innerWidth > 900 && state.drawerOpen) closeDrawer();
    }, 150);
});

// ---------- Bootstrap ----------
fetchSignals().then(function() {
    loadPositions();
    if (state.signals.length > 0) {
        selectPair(state.signals[0].pair);
    }
});