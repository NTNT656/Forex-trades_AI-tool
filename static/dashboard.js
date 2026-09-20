// Dashboard — responsive positions view (parser-safe)

function updateClock() {
    var now = new Date();
    var t = document.getElementById('mtClock');
    var d = document.getElementById('mtDate');
    if (t) t.textContent = now.toTimeString().slice(0, 8);
    if (d) d.textContent = now.toISOString().slice(0, 10).split('-').join('.');
}
setInterval(updateClock, 1000);
updateClock();

function loadPositions() {
    return fetch('/api/open_trades')
        .then(function(r) { return r.json(); })
        .then(function(trades) { renderPositions(trades); })
        .catch(function(err) { console.error(err); });
}

function renderPositions(trades) {
    var tbody = document.getElementById('posBody');
    if (tbody) {
        if (!trades || trades.length === 0) {
            tbody.innerHTML = '<tr><td colspan="12" class="mt-empty">You don\'t have any positions</td></tr>';
        } else {
            tbody.innerHTML = '';
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
                tbody.appendChild(tr);
            });
            tbody.querySelectorAll('.mt-close-btn').forEach(function(btn) {
                btn.addEventListener('click', function() { closeTrade(btn.dataset.id); });
            });
        }
    }

    var cards = document.getElementById('posCards');
    if (cards) {
        if (!trades || trades.length === 0) {
            cards.innerHTML = '<div class="mt-empty">You don\'t have any positions</div>';
        } else {
            cards.innerHTML = '';
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
                cards.appendChild(card);
            });
            cards.querySelectorAll('.pc-close').forEach(function(btn) {
                btn.addEventListener('click', function() { closeTrade(btn.dataset.id); });
            });
        }
    }

    var totalPnl = 0;
    (trades || []).forEach(function(t) { totalPnl += (t.pnl || 0); });
    var eq = 100000 + totalPnl;

    var accPositions = document.getElementById('accPositions');
    var accPnl = document.getElementById('accPnl');
    var accEquity = document.getElementById('accEquity');
    if (accPositions) accPositions.textContent = (trades || []).length;
    if (accPnl) {
        accPnl.textContent = totalPnl.toFixed(2);
        accPnl.style.color = totalPnl >= 0 ? '#00b300' : '#ff3333';
    }
    if (accEquity) accEquity.textContent = eq.toFixed(2);

    var mEq = document.getElementById('mEqDash');
    var mPnl = document.getElementById('mPnlDash');
    var mPos = document.getElementById('mPosDash');
    if (mEq) mEq.textContent = eq.toFixed(2);
    if (mPnl) {
        mPnl.textContent = (totalPnl >= 0 ? '+' : '') + totalPnl.toFixed(2);
        var col = '#e8e8e8';
        if (totalPnl > 0) col = '#00b300';
        else if (totalPnl < 0) col = '#ff3333';
        mPnl.style.color = col;
    }
    if (mPos) mPos.textContent = (trades || []).length;
}

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

var dashRefresh = document.getElementById('dashRefresh');
if (dashRefresh) dashRefresh.addEventListener('click', loadPositions);

setInterval(loadPositions, 5000);
loadPositions();