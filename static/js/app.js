/* Dobbles.AI Chess Coach — Frontend Application */

const API = '';
let currentView = 'dashboard';
let currentGameId = null;
let currentAnalysis = null;
let currentPly = 0;
let drillQueue = [];
let currentDrill = null;

// ── Navigation ──
document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => navigateTo(btn.dataset.view));
});

function navigateTo(view) {
    currentView = view;
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(`view-${view}`).classList.add('active');
    document.querySelector(`[data-view="${view}"]`).classList.add('active');

    if (view === 'dashboard') loadDashboard();
    else if (view === 'games') loadGames();
    else if (view === 'patterns') loadPatterns();
    else if (view === 'drills') loadDrillView();
    else if (view === 'openingbook') loadOpeningBook();
}

// ── Toast Notifications ──
function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

// ── API Helpers ──
async function apiFetch(path, options = {}) {
    try {
        const resp = await fetch(`${API}${path}`, {
            headers: { 'Content-Type': 'application/json', ...options.headers },
            ...options,
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        return await resp.json();
    } catch (e) {
        showToast(e.message, 'error');
        throw e;
    }
}

// ── Dashboard ──
async function loadDashboard() {
    try {
        const [summary, status] = await Promise.all([
            apiFetch('/api/dashboard/summary'),
            apiFetch('/api/analysis/status'),
        ]);

        const kpiGrid = document.getElementById('kpi-grid');
        kpiGrid.innerHTML = `
            <div class="kpi-card">
                <div class="kpi-value">${summary.total_games.toLocaleString()}</div>
                <div class="kpi-label">TOTAL GAMES</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value positive">${summary.win_rate}%</div>
                <div class="kpi-label">WIN RATE</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">${summary.record.wins}-${summary.record.losses}-${summary.record.draws}</div>
                <div class="kpi-label">W / L / D</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value ${summary.avg_cpl && summary.avg_cpl < 50 ? 'positive' : 'negative'}">${summary.avg_cpl ?? '—'}</div>
                <div class="kpi-label">AVG CPL</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value negative">${summary.avg_blunders_per_game != null ? summary.avg_blunders_per_game.toFixed(1) : '—'}</div>
                <div class="kpi-label">AVG BLUNDERS/GAME</div>
            </div>
        `;

        // Analysis status
        document.getElementById('analysis-status').innerHTML = `
            <div style="display:flex;align-items:center;gap:16px;">
                <div style="flex:1;background:var(--color-bg);border-radius:4px;height:24px;overflow:hidden;">
                    <div style="width:${status.percent_complete}%;height:100%;background:var(--color-teal);transition:width 500ms;"></div>
                </div>
                <span style="font-weight:700;">${status.analyzed} / ${status.total_games} analyzed (${status.percent_complete}%)</span>
            </div>
        `;

        // Rating chart
        drawRatingChart(summary.rating_trend);
    } catch (e) {
        console.error('Dashboard load failed:', e);
    }
}

function drawRatingChart(data) {
    const canvas = document.getElementById('rating-chart');
    if (!canvas || !data || data.length === 0) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const w = rect.width, h = rect.height;
    const pad = { top: 20, right: 20, bottom: 30, left: 50 };

    const ratings = data.map(d => d.rating).filter(r => r != null);
    if (ratings.length === 0) return;
    const minR = Math.min(...ratings) - 20;
    const maxR = Math.max(...ratings) + 20;

    ctx.clearRect(0, 0, w, h);

    // Grid
    ctx.strokeStyle = 'rgba(255,255,255,0.08)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const y = pad.top + (h - pad.top - pad.bottom) * i / 4;
        ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke();
        ctx.fillStyle = 'rgba(247,251,254,0.5)';
        ctx.font = '11px Montserrat';
        ctx.textAlign = 'right';
        const val = Math.round(maxR - (maxR - minR) * i / 4);
        ctx.fillText(val.toString(), pad.left - 8, y + 4);
    }

    // Line
    ctx.strokeStyle = '#85E4FD';
    ctx.lineWidth = 2;
    ctx.beginPath();
    data.forEach((d, i) => {
        if (d.rating == null) return;
        const x = pad.left + (w - pad.left - pad.right) * i / (data.length - 1);
        const y = pad.top + (h - pad.top - pad.bottom) * (1 - (d.rating - minR) / (maxR - minR));
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Dots for wins/losses
    data.forEach((d, i) => {
        if (d.rating == null) return;
        const x = pad.left + (w - pad.left - pad.right) * i / (data.length - 1);
        const y = pad.top + (h - pad.top - pad.bottom) * (1 - (d.rating - minR) / (maxR - minR));
        ctx.beginPath();
        ctx.arc(x, y, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = d.result === 'win' ? '#00B98E' : d.result === 'loss' ? '#DB5461' : '#225A8E';
        ctx.fill();
    });
}

// ── Games List ──
let gamesPage = 1;

async function loadGames(page = 1) {
    gamesPage = page;
    const timeClass = document.getElementById('filter-time-class').value;
    const result = document.getElementById('filter-result').value;
    let url = `/api/games?page=${page}&per_page=50`;
    if (timeClass) url += `&time_class=${timeClass}`;
    if (result) url += `&result=${result}`;

    try {
        const data = await apiFetch(url);
        const tbody = document.getElementById('games-table-body');
        tbody.innerHTML = data.games.map(g => `
            <tr onclick="openGameReview(${g.id})">
                <td>${g.end_time ? new Date(g.end_time).toLocaleDateString() : '—'}</td>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${g.opening_name || '—'}</td>
                <td>${g.player_color === 'white' ? '&#9812;' : '&#9818;'}</td>
                <td><span class="badge badge-${g.result}">${g.result}</span></td>
                <td>${g.player_rating || '—'}</td>
                <td>${g.opponent_rating || '—'}</td>
                <td>${g.total_moves || '—'}</td>
                <td>${g.has_analysis ? '<span style="color:var(--color-teal);">&#10003;</span>' : '—'}</td>
                <td>
                    ${g.has_analysis
                        ? `<button class="btn btn-primary btn-sm" onclick="event.stopPropagation();openGameReview(${g.id})">Review</button>`
                        : `<button class="btn btn-secondary btn-sm" onclick="event.stopPropagation();analyzeGame(${g.id})">Analyze</button>`
                    }
                </td>
            </tr>
        `).join('');

        // Pagination
        const pagDiv = document.getElementById('games-pagination');
        let pagHTML = '';
        if (data.pages > 1) {
            if (page > 1) pagHTML += `<button class="btn btn-secondary btn-sm" onclick="loadGames(${page - 1})">Prev</button>`;
            pagHTML += `<span style="padding:8px;color:var(--color-text-dim);">Page ${page} of ${data.pages} (${data.total} games)</span>`;
            if (page < data.pages) pagHTML += `<button class="btn btn-secondary btn-sm" onclick="loadGames(${page + 1})">Next</button>`;
        }
        pagDiv.innerHTML = pagHTML;
    } catch (e) {
        console.error('Failed to load games:', e);
    }
}

// ── Sync Games ──
async function syncGames() {
    showToast('Syncing games from Chess.com...');
    try {
        const result = await apiFetch('/api/games/sync', { method: 'POST' });
        showToast(`Sync complete: ${result.new_games} new games imported, ${result.skipped} skipped.`);
        if (currentView === 'dashboard') loadDashboard();
        if (currentView === 'games') loadGames();
    } catch (e) {
        showToast('Sync failed: ' + e.message, 'error');
    }
}

// ── Analyze Game ──
async function analyzeGame(gameId) {
    showToast(`Starting analysis for game ${gameId}...`);
    try {
        const result = await apiFetch('/api/analysis/batch', {
            method: 'POST',
            body: JSON.stringify({ game_ids: [gameId] }),
        });
        showToast(`Analysis complete. ${result.completed} game(s) analyzed.`);
        loadGames(gamesPage);
    } catch (e) {
        showToast('Analysis failed: ' + e.message, 'error');
    }
}

// ── Game Review ──
async function openGameReview(gameId) {
    currentGameId = gameId;
    navigateTo('review');

    document.getElementById('review-select').style.display = 'none';
    document.getElementById('review-content').style.display = 'block';

    try {
        const [game, analysis] = await Promise.all([
            apiFetch(`/api/games/${gameId}`),
            apiFetch(`/api/analysis/game/${gameId}`).catch(() => null),
        ]);

        // Header
        document.getElementById('review-header').innerHTML = `
            <div>
                <span style="font-weight:700;font-size:16px;">${game.opening_name || 'Unknown Opening'}</span>
                <span style="color:var(--color-text-dim);margin-left:12px;">
                    ${game.player_color === 'white' ? '&#9812;' : '&#9818;'} as ${game.player_color}
                    &nbsp;|&nbsp;
                    <span class="badge badge-${game.result}">${game.result}</span>
                    &nbsp;(${game.result_type})
                    &nbsp;|&nbsp;
                    ${game.player_rating} vs ${game.opponent_rating}
                    &nbsp;|&nbsp;
                    ${game.end_time ? new Date(game.end_time).toLocaleDateString() : ''}
                </span>
            </div>
        `;

        // Summary
        if (game.summary) {
            document.getElementById('game-summary-text').innerHTML = `
                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:8px;">
                    <div style="text-align:center;">
                        <div style="font-size:20px;font-weight:700;">${game.summary.avg_centipawn_loss}</div>
                        <div style="font-size:10px;color:var(--color-sky);">AVG CPL</div>
                    </div>
                    <div style="text-align:center;">
                        <div style="font-size:20px;font-weight:700;color:var(--color-red);">${game.summary.blunder_count}</div>
                        <div style="font-size:10px;color:var(--color-sky);">BLUNDERS</div>
                    </div>
                    <div style="text-align:center;">
                        <div style="font-size:20px;font-weight:700;color:#d4772c;">${game.summary.mistake_count}</div>
                        <div style="font-size:10px;color:var(--color-sky);">MISTAKES</div>
                    </div>
                </div>
                ${game.summary.coaching_notes ? `<div style="border-top:1px solid var(--color-border);padding-top:8px;font-size:12px;line-height:1.6;">${formatCoaching(game.summary.coaching_notes)}</div>` : ''}
            `;
        }

        // Build move list and board
        currentAnalysis = analysis;
        if (analysis) {
            buildMoveList(analysis.moves, game.summary?.critical_moments || []);
            currentPly = 0;
            renderBoard(analysis.moves, 0, game.player_color);
        }
    } catch (e) {
        console.error('Failed to load game review:', e);
    }
}

function buildMoveList(moves, criticalPlies) {
    const container = document.getElementById('move-list');
    let html = '';
    const critSet = new Set(criticalPlies);

    for (let i = 0; i < moves.length; i += 2) {
        const white = moves[i];
        const black = moves[i + 1];
        const mn = white.move_number;

        html += `<div class="move-row">`;
        html += `<span class="move-num">${mn}.</span>`;

        html += `<span class="move-cell ${white.classification || ''} ${critSet.has(white.ply) ? 'critical' : ''}"
                       data-ply="${white.ply}" onclick="goToPly(${white.ply})">
                    ${white.move_played_san}
                 </span>`;

        if (black) {
            html += `<span class="move-cell ${black.classification || ''} ${critSet.has(black.ply) ? 'critical' : ''}"
                           data-ply="${black.ply}" onclick="goToPly(${black.ply})">
                        ${black.move_played_san}
                     </span>`;
        } else {
            html += `<span></span>`;
        }

        html += `</div>`;
    }

    container.innerHTML = html;
}

function goToPly(ply) {
    currentPly = ply;
    if (!currentAnalysis) return;

    // Highlight active move
    document.querySelectorAll('.move-cell').forEach(c => c.classList.remove('active'));
    const activeCell = document.querySelector(`[data-ply="${ply}"]`);
    if (activeCell) {
        activeCell.classList.add('active');
        activeCell.scrollIntoView({ block: 'nearest' });
    }

    const move = currentAnalysis.moves.find(m => m.ply === ply);
    if (!move) return;

    renderBoard(currentAnalysis.moves, ply, currentAnalysis.player_color);
    updateEvalBar(move.eval_before, move.eval_after);

    // If it's a player move with a mistake/blunder, auto-fetch coaching
    if (move.is_player_move && move.classification &&
        ['inaccuracy', 'mistake', 'blunder'].includes(move.classification)) {
        fetchMoveCoaching(currentGameId, ply, move);
    } else {
        document.getElementById('coaching-content').innerHTML = `
            <h3>${move.move_played_san} (${move.classification || 'N/A'})</h3>
            <p>Eval: ${move.eval_before != null ? move.eval_before.toFixed(0) : '?'} → ${move.eval_after != null ? move.eval_after.toFixed(0) : '?'}</p>
            ${move.best_move_san && move.best_move_san !== move.move_played_san
                ? `<p>Best move was: <span class="notation">${move.best_move_san}</span></p>`
                : `<p style="color:var(--color-teal);">This was the best move (or very close to it).</p>`
            }
            ${move.top_3_lines ? `<p style="font-size:12px;color:var(--color-text-dim);">Top lines: ${move.top_3_lines.map(l => l.moves.join(' ')).join(' | ')}</p>` : ''}
        `;
    }
}

async function fetchMoveCoaching(gameId, ply, move) {
    const panel = document.getElementById('coaching-content');
    panel.innerHTML = `<div class="loading"><div class="spinner"></div>Getting coaching...</div>`;
    try {
        const result = await apiFetch('/api/coach/move-explain', {
            method: 'POST',
            body: JSON.stringify({ game_id: gameId, ply: ply }),
        });
        panel.innerHTML = `
            <h3>Move ${move.move_number}: ${move.move_played_san} → ${result.best_move || '?'}</h3>
            <div class="badge badge-${result.classification}" style="margin-bottom:12px;">${result.classification}</div>
            <div style="line-height:1.7;">${formatCoaching(result.coaching)}</div>
        `;
    } catch (e) {
        panel.innerHTML = `<p style="color:var(--color-red);">Failed to load coaching: ${e.message}</p>`;
    }
}

async function requestGameReview() {
    if (!currentGameId) return;
    document.getElementById('btn-coach-review').disabled = true;
    document.getElementById('btn-coach-review').textContent = 'Generating...';
    try {
        const result = await apiFetch(`/api/coach/game-review/${currentGameId}`, { method: 'POST' });
        document.getElementById('game-summary-text').innerHTML += `
            <div style="border-top:1px solid var(--color-border);padding-top:8px;margin-top:8px;">
                ${formatCoaching(result.review)}
            </div>
        `;
        showToast('Game review generated.');
    } catch (e) {
        showToast('Review failed: ' + e.message, 'error');
    } finally {
        document.getElementById('btn-coach-review').disabled = false;
        document.getElementById('btn-coach-review').textContent = 'Get AI Review';
    }
}

function updateEvalBar(evalBefore, evalAfter) {
    const eval_val = evalAfter ?? evalBefore ?? 0;
    // Clamp to -500..500, map to 0..100%
    const clamped = Math.max(-500, Math.min(500, eval_val));
    const pct = 50 + (clamped / 500) * 50;
    document.getElementById('eval-bar').style.width = `${pct}%`;
    const label = Math.abs(eval_val) >= 10000
        ? (eval_val > 0 ? 'M+' : 'M-')
        : (eval_val / 100).toFixed(1);
    document.getElementById('eval-label').textContent = label;
}

function boardNav(dir) {
    if (!currentAnalysis || !currentAnalysis.moves.length) return;
    const maxPly = currentAnalysis.moves[currentAnalysis.moves.length - 1].ply;
    if (dir === 'start') goToPly(currentAnalysis.moves[0].ply);
    else if (dir === 'end') goToPly(maxPly);
    else if (dir === 'prev' && currentPly > 1) goToPly(currentPly - 1);
    else if (dir === 'next' && currentPly < maxPly) goToPly(currentPly + 1);
}

// Keyboard navigation
document.addEventListener('keydown', e => {
    if (currentView !== 'review' || !currentAnalysis) return;
    if (e.key === 'ArrowLeft') { e.preventDefault(); boardNav('prev'); }
    if (e.key === 'ArrowRight') { e.preventDefault(); boardNav('next'); }
    if (e.key === 'Home') { e.preventDefault(); boardNav('start'); }
    if (e.key === 'End') { e.preventDefault(); boardNav('end'); }
});

// ── Simple text-based board renderer ──
function renderBoard(moves, ply, playerColor) {
    // Reconstruct position from FEN at this ply
    let fen;
    if (ply === 0) {
        fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR';
    } else {
        const move = moves.find(m => m.ply === ply);
        if (move && move.fen_before) {
            // fen_before is the position BEFORE the move. We want after.
            // Use the next move's fen_before, or the last known position.
            const nextMove = moves.find(m => m.ply === ply + 1);
            if (nextMove) {
                fen = nextMove.fen_before.split(' ')[0];
            } else {
                // Last move — reconstruct from fen_before
                fen = move.fen_before.split(' ')[0];
            }
        } else {
            fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR';
        }
    }

    const container = document.getElementById('chess-board');
    const pieces = {
        'K': '&#9812;', 'Q': '&#9813;', 'R': '&#9814;', 'B': '&#9815;', 'N': '&#9816;', 'P': '&#9817;',
        'k': '&#9818;', 'q': '&#9819;', 'r': '&#9820;', 'b': '&#9821;', 'n': '&#9822;', 'p': '&#9823;',
    };

    const rows = fen.split('/');
    let board = [];
    for (const row of rows) {
        let boardRow = [];
        for (const ch of row) {
            if (ch >= '1' && ch <= '8') {
                for (let i = 0; i < parseInt(ch); i++) boardRow.push('');
            } else {
                boardRow.push(ch);
            }
        }
        board.push(boardRow);
    }

    if (playerColor === 'black') {
        board = board.reverse().map(r => r.reverse());
    }

    const files = playerColor === 'black' ? 'hgfedcba' : 'abcdefgh';
    const ranks = playerColor === 'black' ? '12345678' : '87654321';

    let html = '<div style="display:grid;grid-template-columns:repeat(8,1fr);width:100%;height:100%;font-size:0;">';
    for (let r = 0; r < 8; r++) {
        for (let c = 0; c < 8; c++) {
            const isLight = (r + c) % 2 === 0;
            const bg = isLight ? '#B58863' : '#F0D9B5';
            const piece = board[r][c];
            html += `<div style="background:${bg};display:flex;align-items:center;justify-content:center;font-size:36px;position:relative;">
                ${piece ? pieces[piece] : ''}
                ${r === 7 ? `<span style="position:absolute;bottom:1px;right:3px;font-size:9px;color:${isLight ? '#F0D9B5' : '#B58863'};font-weight:700;">${files[c]}</span>` : ''}
                ${c === 0 ? `<span style="position:absolute;top:1px;left:3px;font-size:9px;color:${isLight ? '#F0D9B5' : '#B58863'};font-weight:700;">${ranks[r]}</span>` : ''}
            </div>`;
        }
    }
    html += '</div>';
    container.innerHTML = html;
}

// ── Patterns View ──
async function loadPatterns() {
    try {
        const [patterns, openings, timeData] = await Promise.all([
            apiFetch('/api/dashboard/patterns'),
            apiFetch('/api/dashboard/openings'),
            apiFetch('/api/dashboard/time-analysis'),
        ]);

        // Phase performance chart
        drawBarChart('phase-chart', {
            labels: ['Opening', 'Middlegame', 'Endgame'],
            values: [
                patterns.phase_performance.opening ?? 0,
                patterns.phase_performance.middlegame ?? 0,
                patterns.phase_performance.endgame ?? 0,
            ],
            color: '#85E4FD',
            label: 'CPL',
            lowerIsBetter: true,
        });

        // Color stats
        const cs = patterns.color_performance;
        document.getElementById('color-stats').innerHTML = `
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:8px;">
                <div style="text-align:center;padding:20px;background:var(--color-bg);border-radius:8px;">
                    <div style="font-size:32px;">&#9812;</div>
                    <div style="font-size:24px;font-weight:700;margin:8px 0;">${cs.white.win_rate}%</div>
                    <div style="font-size:11px;color:var(--color-sky);">WIN RATE AS WHITE</div>
                    <div style="font-size:12px;color:var(--color-text-dim);margin-top:4px;">${cs.white.games} games | ${cs.white.avg_cpl ?? '—'} CPL</div>
                </div>
                <div style="text-align:center;padding:20px;background:var(--color-bg);border-radius:8px;">
                    <div style="font-size:32px;">&#9818;</div>
                    <div style="font-size:24px;font-weight:700;margin:8px 0;">${cs.black.win_rate}%</div>
                    <div style="font-size:11px;color:var(--color-sky);">WIN RATE AS BLACK</div>
                    <div style="font-size:12px;color:var(--color-text-dim);margin-top:4px;">${cs.black.games} games | ${cs.black.avg_cpl ?? '—'} CPL</div>
                </div>
            </div>
        `;

        // Openings table
        document.getElementById('openings-table-body').innerHTML = openings.openings.map(o => `
            <tr>
                <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;">${o.opening_name}</td>
                <td>${o.eco || '—'}</td>
                <td>${o.games}</td>
                <td><span class="${o.win_rate > 55 ? 'positive' : o.win_rate < 45 ? 'negative' : ''}" style="font-weight:700;">${o.win_rate}%</span></td>
                <td>${o.avg_cpl ?? '—'}</td>
            </tr>
        `).join('');

        // Time of day chart
        if (timeData.by_hour.length) {
            drawBarChart('hour-chart', {
                labels: timeData.by_hour.map(h => `${h.hour}:00`),
                values: timeData.by_hour.map(h => h.win_rate),
                color: '#00B98E',
                label: 'Win %',
                baseline: 50,
            });
        }

        // Day of week chart
        if (timeData.by_day.length) {
            drawBarChart('day-chart', {
                labels: timeData.by_day.map(d => d.day.substring(0, 3)),
                values: timeData.by_day.map(d => d.win_rate),
                color: '#3273DB',
                label: 'Win %',
                baseline: 50,
            });
        }

    } catch (e) {
        console.error('Failed to load patterns:', e);
    }
}

function drawBarChart(canvasId, { labels, values, color, label, baseline, lowerIsBetter }) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const w = rect.width, h = rect.height;
    const pad = { top: 20, right: 20, bottom: 40, left: 50 };

    if (!values.length) return;
    const maxVal = Math.max(...values, baseline || 0) * 1.1;
    const minVal = 0;

    ctx.clearRect(0, 0, w, h);

    const barW = Math.min(40, (w - pad.left - pad.right) / values.length * 0.6);
    const gap = (w - pad.left - pad.right) / values.length;

    // Baseline
    if (baseline != null) {
        const by = pad.top + (h - pad.top - pad.bottom) * (1 - (baseline - minVal) / (maxVal - minVal));
        ctx.strokeStyle = 'rgba(255,255,255,0.2)';
        ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(pad.left, by); ctx.lineTo(w - pad.right, by); ctx.stroke();
        ctx.setLineDash([]);
    }

    values.forEach((v, i) => {
        const x = pad.left + gap * i + (gap - barW) / 2;
        const barH = (h - pad.top - pad.bottom) * (v - minVal) / (maxVal - minVal);
        const y = pad.top + (h - pad.top - pad.bottom) - barH;

        let barColor = color;
        if (lowerIsBetter) {
            barColor = v < 30 ? '#00B98E' : v < 60 ? '#85E4FD' : v < 100 ? '#c4a32e' : '#DB5461';
        } else if (baseline != null) {
            barColor = v >= baseline ? '#00B98E' : '#DB5461';
        }

        ctx.fillStyle = barColor;
        ctx.fillRect(x, y, barW, barH);

        // Value label
        ctx.fillStyle = 'rgba(247,251,254,0.8)';
        ctx.font = '11px Montserrat';
        ctx.textAlign = 'center';
        ctx.fillText(v.toFixed(lowerIsBetter ? 0 : 1), x + barW / 2, y - 6);

        // Axis label
        ctx.fillStyle = 'rgba(247,251,254,0.5)';
        ctx.font = '10px Montserrat';
        ctx.fillText(labels[i], x + barW / 2, h - pad.bottom + 16);
    });

    // Y axis label
    ctx.save();
    ctx.fillStyle = 'rgba(247,251,254,0.5)';
    ctx.font = '10px Montserrat';
    ctx.textAlign = 'center';
    ctx.translate(12, (h - pad.top - pad.bottom) / 2 + pad.top);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(label, 0, 0);
    ctx.restore();
}

async function generateDiagnosis() {
    showToast('Generating pattern diagnosis with Claude Opus...');
    try {
        const result = await apiFetch('/api/coach/diagnose', { method: 'POST' });
        document.getElementById('diagnosis-card').style.display = 'block';
        document.getElementById('diagnosis-text').innerHTML = formatCoaching(result.diagnosis);
        showToast('Diagnosis complete.');
        if (currentView !== 'patterns') navigateTo('patterns');
    } catch (e) {
        showToast('Diagnosis failed: ' + e.message, 'error');
    }
}

// ── Drills View ──
async function loadDrillView() {
    try {
        const stats = await apiFetch('/api/drills/stats');
        document.getElementById('drill-kpis').innerHTML = `
            <div class="kpi-card">
                <div class="kpi-value">${stats.total_drills}</div>
                <div class="kpi-label">TOTAL DRILLS</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">${stats.due_today || 0}</div>
                <div class="kpi-label">DUE TODAY</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value positive">${stats.overall_accuracy ?? '—'}%</div>
                <div class="kpi-label">ACCURACY</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">${stats.mastered || 0}</div>
                <div class="kpi-label">MASTERED</div>
            </div>
        `;
        loadDrills();
    } catch (e) {
        console.error('Failed to load drill stats:', e);
    }
}

async function loadDrills() {
    try {
        const data = await apiFetch('/api/drills?count=20');
        drillQueue = data.drills;
        renderDrillQueue();
        if (drillQueue.length > 0) {
            loadDrill(0);
        } else {
            document.getElementById('drill-prompt').textContent = 'No drills available. Extract drills from analyzed games first.';
        }
    } catch (e) {
        console.error('Failed to load drills:', e);
    }
}

function renderDrillQueue() {
    const container = document.getElementById('drill-queue');
    if (!drillQueue.length) {
        container.innerHTML = '<p style="color:var(--color-text-dim);padding:8px;">No drills in queue.</p>';
        return;
    }
    container.innerHTML = drillQueue.map((d, i) => `
        <div style="display:flex;justify-content:space-between;padding:8px;border-bottom:1px solid var(--color-border);cursor:pointer;${currentDrill && currentDrill.id === d.id ? 'background:rgba(255,255,255,0.05);' : ''}" onclick="loadDrill(${i})">
            <span style="font-size:12px;">${d.opening_name || 'Position'} (${d.game_phase || '?'})</span>
            <span style="font-size:11px;color:var(--color-text-dim);">${d.accuracy != null ? d.accuracy + '%' : 'new'}</span>
        </div>
    `).join('');
}

function loadDrill(index) {
    if (index >= drillQueue.length) return;
    currentDrill = drillQueue[index];

    document.getElementById('drill-prompt').textContent = 'Find the best move!';
    document.getElementById('drill-answer').value = '';
    document.getElementById('drill-feedback').style.display = 'none';
    document.getElementById('btn-next-drill').style.display = 'none';

    // Render board from FEN
    renderDrillBoard(currentDrill.fen, currentDrill.player_color);
    renderDrillQueue();
}

function renderDrillBoard(fen, playerColor) {
    const fenBoard = fen.split(' ')[0];
    const container = document.getElementById('drill-board');
    const pieces = {
        'K': '&#9812;', 'Q': '&#9813;', 'R': '&#9814;', 'B': '&#9815;', 'N': '&#9816;', 'P': '&#9817;',
        'k': '&#9818;', 'q': '&#9819;', 'r': '&#9820;', 'b': '&#9821;', 'n': '&#9822;', 'p': '&#9823;',
    };

    const rows = fenBoard.split('/');
    let board = [];
    for (const row of rows) {
        let boardRow = [];
        for (const ch of row) {
            if (ch >= '1' && ch <= '8') {
                for (let i = 0; i < parseInt(ch); i++) boardRow.push('');
            } else {
                boardRow.push(ch);
            }
        }
        board.push(boardRow);
    }

    if (playerColor === 'black') {
        board = board.reverse().map(r => r.reverse());
    }

    const files = playerColor === 'black' ? 'hgfedcba' : 'abcdefgh';
    const ranks = playerColor === 'black' ? '12345678' : '87654321';

    let html = '<div style="display:grid;grid-template-columns:repeat(8,1fr);width:100%;height:100%;font-size:0;">';
    for (let r = 0; r < 8; r++) {
        for (let c = 0; c < 8; c++) {
            const isLight = (r + c) % 2 === 0;
            const bg = isLight ? '#B58863' : '#F0D9B5';
            const piece = board[r][c];
            html += `<div style="background:${bg};display:flex;align-items:center;justify-content:center;font-size:36px;position:relative;">
                ${piece ? pieces[piece] : ''}
                ${r === 7 ? `<span style="position:absolute;bottom:1px;right:3px;font-size:9px;color:${isLight ? '#F0D9B5' : '#B58863'};font-weight:700;">${files[c]}</span>` : ''}
                ${c === 0 ? `<span style="position:absolute;top:1px;left:3px;font-size:9px;color:${isLight ? '#F0D9B5' : '#B58863'};font-weight:700;">${ranks[r]}</span>` : ''}
            </div>`;
        }
    }
    html += '</div>';
    container.innerHTML = html;
}

async function submitDrill() {
    if (!currentDrill) return;
    const answer = document.getElementById('drill-answer').value.trim();
    if (!answer) return;

    try {
        const result = await apiFetch(`/api/drills/${currentDrill.id}/attempt`, {
            method: 'POST',
            body: JSON.stringify({ move_san: answer }),
        });

        const fb = document.getElementById('drill-feedback');
        fb.style.display = 'block';

        if (result.correct) {
            fb.className = 'drill-feedback correct';
            fb.innerHTML = `<strong>Correct!</strong> ${result.correct_move} was the best move.`;
        } else {
            fb.className = 'drill-feedback incorrect';
            fb.innerHTML = `
                <strong>Not quite.</strong> You played <span class="notation">${result.your_move}</span>.
                The best move was <span class="notation">${result.correct_move}</span>.
                <br>In the game, you played <span class="notation">${result.player_move_in_game}</span> (${result.eval_delta ? result.eval_delta.toFixed(0) + ' cp' : ''}).
                ${result.coaching ? `<div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--color-border);">${formatCoaching(result.coaching)}</div>` : ''}
            `;
        }

        document.getElementById('btn-next-drill').style.display = 'block';
    } catch (e) {
        showToast('Failed to submit drill: ' + e.message, 'error');
    }
}

function nextDrill() {
    if (!drillQueue.length) return;
    const currentIndex = drillQueue.findIndex(d => d.id === currentDrill?.id);
    const nextIndex = (currentIndex + 1) % drillQueue.length;
    loadDrill(nextIndex);
}

async function extractDrills() {
    showToast('Extracting drill positions from analyzed games...');
    try {
        const result = await apiFetch('/api/drills/extract', { method: 'POST' });
        showToast(`Extracted ${result.created} new drill positions.`);
        loadDrillView();
    } catch (e) {
        showToast('Extraction failed: ' + e.message, 'error');
    }
}

// ── Opening Book View ──
async function loadOpeningBook() {
    showOpeningList();
    try {
        const data = await apiFetch('/api/dashboard/openings');
        document.getElementById('openingbook-list').innerHTML = data.openings.map(o => `
            <tr onclick="openOpeningDetail('${o.eco}')">
                <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;">${o.opening_name}</td>
                <td>${o.eco || '—'}</td>
                <td>${o.games}</td>
                <td><span class="${o.win_rate > 55 ? 'positive' : o.win_rate < 45 ? 'negative' : ''}" style="font-weight:700;">${o.win_rate}%</span></td>
                <td><button class="btn btn-primary btn-sm" onclick="event.stopPropagation();openOpeningDetail('${o.eco}')">Study</button></td>
            </tr>
        `).join('');
    } catch (e) {
        console.error('Failed to load opening book:', e);
    }
}

function showOpeningList() {
    document.getElementById('openingbook-select').style.display = 'block';
    document.getElementById('openingbook-detail').style.display = 'none';
}

async function openOpeningDetail(eco) {
    document.getElementById('openingbook-select').style.display = 'none';
    document.getElementById('openingbook-detail').style.display = 'block';

    try {
        const data = await apiFetch(`/api/dashboard/opening-book/${eco}`);

        document.getElementById('openingbook-header').innerHTML = `
            <h3 style="font-size:18px;font-weight:700;margin-bottom:8px;">${data.opening_name} <span style="color:var(--color-text-dim);">(${data.eco})</span></h3>
        `;

        document.getElementById('openingbook-kpis').innerHTML = `
            <div class="kpi-card">
                <div class="kpi-value">${data.total_games}</div>
                <div class="kpi-label">GAMES PLAYED</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value ${data.win_rate > 55 ? 'positive' : data.win_rate < 45 ? 'negative' : ''}">${data.win_rate}%</div>
                <div class="kpi-label">WIN RATE</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">${data.avg_cpl ?? '—'}</div>
                <div class="kpi-label">AVG CPL</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">${data.drill_count}</div>
                <div class="kpi-label">DRILL POSITIONS</div>
            </div>
        `;

        // Book moves
        let movesHtml = '<div style="font-size:13px;">';
        for (const bm of data.book_moves) {
            const isWhite = bm.color === 'white';
            const prefix = isWhite ? `<strong>${bm.move_number}.</strong>` : '';
            const altText = bm.alternatives.length
                ? `<span style="color:var(--color-text-muted);font-size:11px;margin-left:4px;">(${bm.alternatives.map(a => `${a.move} ${a.pct}%`).join(', ')})</span>`
                : '';
            movesHtml += `
                <div style="display:inline-block;margin:2px 0;">
                    ${prefix} <span class="notation" style="padding:2px 6px;background:${bm.main_pct > 70 ? 'rgba(0,185,142,0.15)' : bm.main_pct > 40 ? 'rgba(133,228,253,0.1)' : 'rgba(219,84,97,0.1)'};border-radius:3px;">${bm.main_move}</span>
                    <span style="font-size:10px;color:var(--color-text-dim);">${bm.main_pct}%</span>
                    ${altText}
                </div>
            `;
        }
        movesHtml += '</div>';
        document.getElementById('openingbook-moves').innerHTML = movesHtml;

        // Color breakdown
        document.getElementById('openingbook-colors').innerHTML = `
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:8px;">
                <div style="text-align:center;padding:16px;background:var(--color-bg);border-radius:8px;">
                    <div style="font-size:28px;">&#9812;</div>
                    <div style="font-size:20px;font-weight:700;margin:4px 0;">${data.as_white.win_rate}%</div>
                    <div style="font-size:11px;color:var(--color-sky);">${data.as_white.games} GAMES AS WHITE</div>
                </div>
                <div style="text-align:center;padding:16px;background:var(--color-bg);border-radius:8px;">
                    <div style="font-size:28px;">&#9818;</div>
                    <div style="font-size:20px;font-weight:700;margin:4px 0;">${data.as_black.win_rate}%</div>
                    <div style="font-size:11px;color:var(--color-sky);">${data.as_black.games} GAMES AS BLACK</div>
                </div>
            </div>
        `;
    } catch (e) {
        showToast('Failed to load opening: ' + e.message, 'error');
    }
}

// ── Utilities ──
function formatCoaching(text) {
    if (!text) return '';
    return text
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/^/, '<p>') + '</p>';
}

// ── Init ──
loadDashboard();
