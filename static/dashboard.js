// dashboard.js – positions table on the dashboard page

function updateClock() {
    const now = new Date();
    document.getElementById('mtClock').textContent = now.toTimeString().slice(0, 8);
    document.getElementById('mtDate').textContent = now.toISOString().slice(0, 10).replace(/-/g, '.');
}
setInterval(updateClock, 1000);
updateClock();

async function loadPositions() {
    try {
        const resp = await fetch('/api/open_trades');
        const trades = await resp.json();
        renderPositions(trades);
    } catch (err) {
        console.error(err);
    }
}

function renderPositions(trades) {
    const tbody = document.getElementById('posBody');
    if (!trades || trades.length === 0) {
        tbody.innerHTML = `<tr><td colspan="12" class="mt-empty">You don't have any positions</td></tr>`;
        document.getElementById('accPositions').textContent = '0';
        document.getElementById('accPnl').textContent = '0.00';
        return;
    }
    tbody.innerHTML = '';
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
        tbody.appendChild(tr);
    });
    document.querySelectorAll('.mt-close-btn').forEach(btn => {
        btn.addEventListener('click', () => closeTrade(btn.dataset.id));
    });
    document.getElementById('accPositions').textContent = trades.length;
    document.getElementById('accPnl').textContent = totalPnl.toFixed(2);
    document.getElementById('accPnl').style.color = totalPnl >= 0 ? '#00b300' : '#ff3333';
    document.getElementById('accEquity').textContent = (100000 + totalPnl).toFixed(2);
}

async function closeTrade(tradeId) {
    if (!confirm(`Close position #${tradeId}?`)) return;
    try {
        const resp = await fetch('/api/close_trade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ trade_id: tradeId })
        });
        const data = await resp.json();
        if (data.success) loadPositions();
        else alert('Close failed: ' + data.error);
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

setInterval(loadPositions, 5000);
loadPositions();