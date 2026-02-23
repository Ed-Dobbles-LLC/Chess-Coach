/* Dobbles.AI Chess Coach — Frontend Application v2 */

const API = '';
let currentView = 'dashboard';
let currentGameId = null;
let currentAnalysis = null;
let currentPly = 0;
let drillQueue = [];
let currentDrill = null;

// Walkthrough state
let wtData = null;          // Full walkthrough API response
let wtIndex = 0;            // Current commentary point index
let wtAutoplayTimer = null;  // Autoplay interval ID
let wtAutoplayPly = 0;      // Current ply during autoplay
let wtActive = false;        // Whether walkthrough mode is active

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
    else if (view === 'sessions') loadSessions();
    else if (view === 'openingbook') loadOpeningBook();
}

// ── Toast Notifications ──
function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(8px)';
        toast.style.transition = 'all 200ms ease';
        setTimeout(() => toast.remove(), 200);
    }, 3500);
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
            <div class="progress-bar-wrap">
                <div class="progress-bar">
                    <div class="progress-bar-fill" style="width:${status.percent_complete}%;"></div>
                </div>
                <span class="progress-label">${status.analyzed} / ${status.total_games} analyzed (${status.percent_complete}%)</span>
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

    // Grid lines
    ctx.strokeStyle = 'rgba(255,255,255,0.05)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const y = pad.top + (h - pad.top - pad.bottom) * i / 4;
        ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke();
        ctx.fillStyle = 'rgba(148,163,184,0.6)';
        ctx.font = '11px Inter';
        ctx.textAlign = 'right';
        const val = Math.round(maxR - (maxR - minR) * i / 4);
        ctx.fillText(val.toString(), pad.left - 8, y + 4);
    }

    // Area fill
    ctx.beginPath();
    let firstX, firstY;
    data.forEach((d, i) => {
        if (d.rating == null) return;
        const x = pad.left + (w - pad.left - pad.right) * i / (data.length - 1);
        const y = pad.top + (h - pad.top - pad.bottom) * (1 - (d.rating - minR) / (maxR - minR));
        if (i === 0) { ctx.moveTo(x, y); firstX = x; firstY = y; }
        else ctx.lineTo(x, y);
    });
    // Close the area
    const lastX = pad.left + (w - pad.left - pad.right);
    ctx.lineTo(lastX, h - pad.bottom);
    ctx.lineTo(firstX, h - pad.bottom);
    ctx.closePath();
    const gradient = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
    gradient.addColorStop(0, 'rgba(56, 189, 248, 0.12)');
    gradient.addColorStop(1, 'rgba(56, 189, 248, 0.01)');
    ctx.fillStyle = gradient;
    ctx.fill();

    // Line
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.beginPath();
    data.forEach((d, i) => {
        if (d.rating == null) return;
        const x = pad.left + (w - pad.left - pad.right) * i / (data.length - 1);
        const y = pad.top + (h - pad.top - pad.bottom) * (1 - (d.rating - minR) / (maxR - minR));
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Result dots
    data.forEach((d, i) => {
        if (d.rating == null) return;
        const x = pad.left + (w - pad.left - pad.right) * i / (data.length - 1);
        const y = pad.top + (h - pad.top - pad.bottom) * (1 - (d.rating - minR) / (maxR - minR));
        ctx.beginPath();
        ctx.arc(x, y, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = d.result === 'win' ? '#10b981' : d.result === 'loss' ? '#ef4444' : '#3b82f6';
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
                <td class="td-truncate">${g.opening_name || '—'}</td>
                <td>${g.player_color === 'white' ? '&#9812;' : '&#9818;'}</td>
                <td><span class="badge badge-${g.result}">${g.result}</span></td>
                <td>${g.player_rating || '—'}</td>
                <td>${g.opponent_rating || '—'}</td>
                <td>${g.total_moves || '—'}</td>
                <td>${g.has_analysis ? '<span class="check-yes">&#10003;</span>' : '—'}</td>
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
            if (page > 1) pagHTML += `<button class="btn btn-secondary btn-sm" onclick="loadGames(${page - 1})">&#8592; Prev</button>`;
            pagHTML += `<span class="pagination-info">Page ${page} of ${data.pages} (${data.total} games)</span>`;
            if (page < data.pages) pagHTML += `<button class="btn btn-secondary btn-sm" onclick="loadGames(${page + 1})">Next &#8594;</button>`;
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
    // Reset walkthrough state if active
    if (wtActive) exitWalkthrough();

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
                <span class="review-title">${game.opening_name || 'Unknown Opening'}</span>
                <span class="review-meta">
                    ${game.player_color === 'white' ? '&#9812;' : '&#9818;'} as ${game.player_color}
                    <span class="divider"></span>
                    <span class="badge badge-${game.result}">${game.result}</span>
                    (${game.result_type})
                    <span class="divider"></span>
                    ${game.player_rating} vs ${game.opponent_rating}
                    <span class="divider"></span>
                    ${game.end_time ? new Date(game.end_time).toLocaleDateString() : ''}
                </span>
            </div>
        `;

        // Summary
        if (game.summary) {
            document.getElementById('game-summary-text').innerHTML = `
                <div class="game-summary-stats">
                    <div class="summary-stat">
                        <div class="summary-stat-value">${game.summary.avg_centipawn_loss}</div>
                        <div class="summary-stat-label">AVG CPL</div>
                    </div>
                    <div class="summary-stat">
                        <div class="summary-stat-value" style="color:var(--color-red);">${game.summary.blunder_count}</div>
                        <div class="summary-stat-label">BLUNDERS</div>
                    </div>
                    <div class="summary-stat">
                        <div class="summary-stat-value" style="color:var(--color-orange);">${game.summary.mistake_count}</div>
                        <div class="summary-stat-label">MISTAKES</div>
                    </div>
                </div>
                ${game.summary.coaching_notes ? `<div class="summary-notes">${formatCoaching(game.summary.coaching_notes)}</div>` : ''}
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

    // In walkthrough mode, don't overwrite the coaching panel from individual move clicks
    if (wtActive) return;

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
            ${move.top_3_lines ? `<p style="font-size:12px;color:var(--color-text-muted);">Top lines: ${move.top_3_lines.map(l => l.moves.join(' ')).join(' | ')}</p>` : ''}
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
            <div style="line-height:1.75;">${formatCoaching(result.coaching)}</div>
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
            <div class="summary-notes" style="margin-top:8px;">
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

// ── Walkthrough ──
async function startWalkthrough() {
    if (!currentGameId || !currentAnalysis) return;
    const btn = document.getElementById('btn-walkthrough');
    btn.disabled = true;
    btn.textContent = 'Loading...';

    try {
        wtData = await apiFetch(`/api/coach/walkthrough/${currentGameId}`, { method: 'POST' });
        if (!wtData.commentary_points || wtData.commentary_points.length === 0) {
            showToast('No commentary points found for this game.', 'error');
            return;
        }
        wtActive = true;
        wtIndex = 0;

        // Show walkthrough UI
        document.getElementById('walkthrough-container').style.display = 'block';

        // Render story banner
        const banner = document.getElementById('wt-story-banner');
        banner.innerHTML = `
            <span class="wt-story-label">Game Story</span>
            ${wtData.narrative_summary || 'Walkthrough ready.'}
        `;

        // Jump to first commentary point
        wtGoToMoment(0);
    } catch (e) {
        showToast('Walkthrough failed: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Walkthrough';
    }
}

function exitWalkthrough() {
    wtActive = false;
    wtData = null;
    wtStopAutoplay();
    document.getElementById('walkthrough-container').style.display = 'none';
    document.getElementById('wt-autoplay').checked = false;

    // Restore normal coaching panel
    document.getElementById('coaching-content').innerHTML = `
        <h3>COACHING</h3>
        <p>Click any move to get AI coaching explanation.</p>
    `;
}

function wtGoToMoment(index) {
    if (!wtData || !wtData.commentary_points.length) return;
    wtIndex = Math.max(0, Math.min(index, wtData.commentary_points.length - 1));
    const cp = wtData.commentary_points[wtIndex];

    // Update progress indicator
    document.getElementById('wt-progress').innerHTML = `
        Moment <span class="wt-moment-num">${wtIndex + 1}</span> of <span class="wt-moment-num">${wtData.commentary_points.length}</span>
    `;

    // Update prev/next button states
    document.getElementById('wt-btn-prev').disabled = wtIndex === 0;
    document.getElementById('wt-btn-next').disabled = wtIndex === wtData.commentary_points.length - 1;

    // Jump board to this ply
    goToPly(cp.ply);

    // Pulse animation
    const boardEl = document.getElementById('chess-board');
    boardEl.classList.remove('wt-pulse');
    void boardEl.offsetWidth; // force reflow
    boardEl.classList.add('wt-pulse');

    // Render coaching commentary
    renderWtCommentary(cp);
}

function renderWtCommentary(cp) {
    const panel = document.getElementById('coaching-content');

    const evalBefore = cp.eval_before != null ? cp.eval_before : 0;
    const evalAfter = cp.eval_after != null ? cp.eval_after : 0;
    const evalBeforeDisplay = Math.abs(evalBefore) >= 10000
        ? (evalBefore > 0 ? 'M+' : 'M-') : (evalBefore / 100).toFixed(1);
    const evalAfterDisplay = Math.abs(evalAfter) >= 10000
        ? (evalAfter > 0 ? 'M+' : 'M-') : (evalAfter / 100).toFixed(1);
    const evalBeforeClass = evalBefore > 20 ? 'positive' : evalBefore < -20 ? 'negative' : '';
    const evalAfterClass = evalAfter > 20 ? 'positive' : evalAfter < -20 ? 'negative' : '';

    const colorIcon = cp.color === 'white' ? '&#9812;' : '&#9818;';
    const moveLabel = `${cp.move_number}${cp.color === 'white' ? '.' : '...'} ${cp.move_played}`;

    // Badge type — use the type field from API
    const badgeType = cp.type || cp.classification || '';
    const badgeLabel = badgeType.replace(/_/g, ' ');

    // Best move comparison
    const showBest = cp.best_move && cp.best_move !== cp.move_played;

    panel.innerHTML = `
        <div class="wt-coaching-header">
            <span style="font-size:22px;">${colorIcon}</span>
            <span class="wt-move-label">${moveLabel}</span>
            <span class="wt-classification-badge ${badgeType}">${badgeLabel}</span>
        </div>
        <div class="wt-eval-row">
            <span class="wt-eval-val ${evalBeforeClass}">${evalBeforeDisplay}</span>
            <span class="wt-arrow">&#8594;</span>
            <span class="wt-eval-val ${evalAfterClass}">${evalAfterDisplay}</span>
            <span style="margin-left:8px;color:var(--color-text-muted);">${cp.game_phase || ''}</span>
        </div>
        ${showBest ? `<div class="wt-moves-row">
            Played <span class="notation">${cp.move_played}</span>
            &nbsp;&middot;&nbsp; Best was <span class="notation">${cp.best_move}</span>
        </div>` : ''}
        <div class="wt-commentary-text">${cp.commentary}</div>
    `;
}

function wtNav(dir) {
    if (!wtData) return;
    // If autoplay is running, stop it
    wtStopAutoplay();
    document.getElementById('wt-autoplay').checked = false;

    if (dir === 'prev') wtGoToMoment(wtIndex - 1);
    else if (dir === 'next') wtGoToMoment(wtIndex + 1);
}

function wtToggleAutoplay() {
    const checked = document.getElementById('wt-autoplay').checked;
    if (checked) {
        wtStartAutoplay();
    } else {
        wtStopAutoplay();
    }
}

function wtStartAutoplay() {
    if (!wtData || !currentAnalysis) return;

    // Start from ply 1 (or current commentary point's ply)
    const cp = wtData.commentary_points[wtIndex];
    wtAutoplayPly = wtIndex === 0 ? 0 : cp.ply;

    // Build a set of commentary plies for quick lookup
    const commentaryPlies = new Set(wtData.commentary_points.map(c => c.ply));

    const maxPly = currentAnalysis.moves[currentAnalysis.moves.length - 1].ply;

    wtAutoplayTimer = setInterval(() => {
        wtAutoplayPly++;
        if (wtAutoplayPly > maxPly) {
            wtStopAutoplay();
            document.getElementById('wt-autoplay').checked = false;
            return;
        }

        // Navigate board
        goToPly(wtAutoplayPly);

        // If this is a commentary point, pause and show it
        if (commentaryPlies.has(wtAutoplayPly)) {
            const cpIdx = wtData.commentary_points.findIndex(c => c.ply === wtAutoplayPly);
            if (cpIdx >= 0) {
                wtIndex = cpIdx;

                // Update progress
                document.getElementById('wt-progress').innerHTML = `
                    Moment <span class="wt-moment-num">${wtIndex + 1}</span> of <span class="wt-moment-num">${wtData.commentary_points.length}</span>
                `;
                document.getElementById('wt-btn-prev').disabled = wtIndex === 0;
                document.getElementById('wt-btn-next').disabled = wtIndex === wtData.commentary_points.length - 1;

                // Pulse
                const boardEl = document.getElementById('chess-board');
                boardEl.classList.remove('wt-pulse');
                void boardEl.offsetWidth;
                boardEl.classList.add('wt-pulse');

                renderWtCommentary(wtData.commentary_points[cpIdx]);

                // Pause for 5 seconds at commentary points, then resume
                clearInterval(wtAutoplayTimer);
                wtAutoplayTimer = setTimeout(() => {
                    // Resume autoplay after pause
                    if (document.getElementById('wt-autoplay').checked) {
                        wtStartAutoplayFrom(wtAutoplayPly);
                    }
                }, 5000);
            }
        }
    }, 1000);
}

function wtStartAutoplayFrom(fromPly) {
    if (!wtData || !currentAnalysis) return;
    wtAutoplayPly = fromPly;
    const commentaryPlies = new Set(wtData.commentary_points.map(c => c.ply));
    const maxPly = currentAnalysis.moves[currentAnalysis.moves.length - 1].ply;

    wtAutoplayTimer = setInterval(() => {
        wtAutoplayPly++;
        if (wtAutoplayPly > maxPly) {
            wtStopAutoplay();
            document.getElementById('wt-autoplay').checked = false;
            return;
        }

        goToPly(wtAutoplayPly);

        if (commentaryPlies.has(wtAutoplayPly)) {
            const cpIdx = wtData.commentary_points.findIndex(c => c.ply === wtAutoplayPly);
            if (cpIdx >= 0) {
                wtIndex = cpIdx;
                document.getElementById('wt-progress').innerHTML = `
                    Moment <span class="wt-moment-num">${wtIndex + 1}</span> of <span class="wt-moment-num">${wtData.commentary_points.length}</span>
                `;
                document.getElementById('wt-btn-prev').disabled = wtIndex === 0;
                document.getElementById('wt-btn-next').disabled = wtIndex === wtData.commentary_points.length - 1;

                const boardEl = document.getElementById('chess-board');
                boardEl.classList.remove('wt-pulse');
                void boardEl.offsetWidth;
                boardEl.classList.add('wt-pulse');

                renderWtCommentary(wtData.commentary_points[cpIdx]);

                clearInterval(wtAutoplayTimer);
                wtAutoplayTimer = setTimeout(() => {
                    if (document.getElementById('wt-autoplay').checked) {
                        wtStartAutoplayFrom(wtAutoplayPly);
                    }
                }, 5000);
            }
        }
    }, 1000);
}

function wtStopAutoplay() {
    if (wtAutoplayTimer) {
        clearInterval(wtAutoplayTimer);
        clearTimeout(wtAutoplayTimer);
        wtAutoplayTimer = null;
    }
}

function updateEvalBar(evalBefore, evalAfter) {
    const eval_val = evalAfter ?? evalBefore ?? 0;
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
    // In walkthrough mode, left/right navigate between commentary points
    if (wtActive) {
        if (e.key === 'ArrowLeft') { e.preventDefault(); wtNav('prev'); }
        else if (e.key === 'ArrowRight') { e.preventDefault(); wtNav('next'); }
        else if (e.key === 'Escape') { e.preventDefault(); exitWalkthrough(); }
        return;
    }
    if (e.key === 'ArrowLeft') { e.preventDefault(); boardNav('prev'); }
    if (e.key === 'ArrowRight') { e.preventDefault(); boardNav('next'); }
    if (e.key === 'Home') { e.preventDefault(); boardNav('start'); }
    if (e.key === 'End') { e.preventDefault(); boardNav('end'); }
});

// ── Chess Board Renderer ──
function renderBoard(moves, ply, playerColor) {
    let fen;
    if (ply === 0) {
        fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR';
    } else {
        const move = moves.find(m => m.ply === ply);
        if (move && move.fen_before) {
            const nextMove = moves.find(m => m.ply === ply + 1);
            if (nextMove) {
                fen = nextMove.fen_before.split(' ')[0];
            } else {
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
            const sqClass = isLight ? 'board-square-light' : 'board-square-dark';
            const coordClass = isLight ? 'board-coord-on-light' : 'board-coord-on-dark';
            const piece = board[r][c];
            html += `<div class="board-square ${sqClass}">
                ${piece ? pieces[piece] : ''}
                ${r === 7 ? `<span class="board-coord board-coord-file ${coordClass}">${files[c]}</span>` : ''}
                ${c === 0 ? `<span class="board-coord board-coord-rank ${coordClass}">${ranks[r]}</span>` : ''}
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
            color: '#38bdf8',
            label: 'CPL',
            lowerIsBetter: true,
        });

        // Color stats
        const cs = patterns.color_performance;
        document.getElementById('color-stats').innerHTML = `
            <div class="color-stats-grid">
                <div class="color-stat-card">
                    <div class="color-stat-icon">&#9812;</div>
                    <div class="color-stat-value">${cs.white.win_rate}%</div>
                    <div class="color-stat-label">WIN RATE AS WHITE</div>
                    <div class="color-stat-detail">${cs.white.games} games | ${cs.white.avg_cpl ?? '—'} CPL</div>
                </div>
                <div class="color-stat-card">
                    <div class="color-stat-icon">&#9818;</div>
                    <div class="color-stat-value">${cs.black.win_rate}%</div>
                    <div class="color-stat-label">WIN RATE AS BLACK</div>
                    <div class="color-stat-detail">${cs.black.games} games | ${cs.black.avg_cpl ?? '—'} CPL</div>
                </div>
            </div>
        `;

        // Openings table
        document.getElementById('openings-table-body').innerHTML = openings.openings.map(o => `
            <tr>
                <td class="td-truncate">${o.opening_name}</td>
                <td>${o.eco || '—'}</td>
                <td>${o.games}</td>
                <td><span class="${o.win_rate > 55 ? 'wr-positive' : o.win_rate < 45 ? 'wr-negative' : 'wr-neutral'}">${o.win_rate}%</span></td>
                <td>${o.avg_cpl ?? '—'}</td>
            </tr>
        `).join('');

        // Time of day chart
        if (timeData.by_hour.length) {
            drawBarChart('hour-chart', {
                labels: timeData.by_hour.map(h => `${h.hour}:00`),
                values: timeData.by_hour.map(h => h.win_rate),
                color: '#10b981',
                label: 'Win %',
                baseline: 50,
            });
        }

        // Day of week chart
        if (timeData.by_day.length) {
            drawBarChart('day-chart', {
                labels: timeData.by_day.map(d => d.day.substring(0, 3)),
                values: timeData.by_day.map(d => d.win_rate),
                color: '#3b82f6',
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
    const pad = { top: 24, right: 20, bottom: 40, left: 50 };

    if (!values.length) return;
    const maxVal = Math.max(...values, baseline || 0) * 1.15;
    const minVal = 0;

    ctx.clearRect(0, 0, w, h);

    const barW = Math.min(36, (w - pad.left - pad.right) / values.length * 0.55);
    const gap = (w - pad.left - pad.right) / values.length;

    // Baseline
    if (baseline != null) {
        const by = pad.top + (h - pad.top - pad.bottom) * (1 - (baseline - minVal) / (maxVal - minVal));
        ctx.strokeStyle = 'rgba(255,255,255,0.12)';
        ctx.setLineDash([4, 4]);
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(pad.left, by); ctx.lineTo(w - pad.right, by); ctx.stroke();
        ctx.setLineDash([]);

        // Baseline label
        ctx.fillStyle = 'rgba(148,163,184,0.5)';
        ctx.font = '10px Inter';
        ctx.textAlign = 'right';
        ctx.fillText(`${baseline}%`, pad.left - 6, by + 3);
    }

    values.forEach((v, i) => {
        const x = pad.left + gap * i + (gap - barW) / 2;
        const barH = (h - pad.top - pad.bottom) * (v - minVal) / (maxVal - minVal);
        const y = pad.top + (h - pad.top - pad.bottom) - barH;

        let barColor = color;
        if (lowerIsBetter) {
            barColor = v < 30 ? '#10b981' : v < 60 ? '#38bdf8' : v < 100 ? '#f59e0b' : '#ef4444';
        } else if (baseline != null) {
            barColor = v >= baseline ? '#10b981' : '#ef4444';
        }

        // Bar with rounded top
        const radius = Math.min(4, barW / 2);
        ctx.beginPath();
        ctx.moveTo(x, y + radius);
        ctx.quadraticCurveTo(x, y, x + radius, y);
        ctx.lineTo(x + barW - radius, y);
        ctx.quadraticCurveTo(x + barW, y, x + barW, y + radius);
        ctx.lineTo(x + barW, y + barH);
        ctx.lineTo(x, y + barH);
        ctx.closePath();
        ctx.fillStyle = barColor;
        ctx.fill();

        // Value label
        ctx.fillStyle = 'rgba(241,245,249,0.8)';
        ctx.font = '600 11px Inter';
        ctx.textAlign = 'center';
        ctx.fillText(v.toFixed(lowerIsBetter ? 0 : 1), x + barW / 2, y - 8);

        // Axis label
        ctx.fillStyle = 'rgba(148,163,184,0.6)';
        ctx.font = '10px Inter';
        ctx.fillText(labels[i], x + barW / 2, h - pad.bottom + 16);
    });

    // Y axis label
    ctx.save();
    ctx.fillStyle = 'rgba(148,163,184,0.5)';
    ctx.font = '10px Inter';
    ctx.textAlign = 'center';
    ctx.translate(14, (h - pad.top - pad.bottom) / 2 + pad.top);
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
        container.innerHTML = '<p style="color:var(--color-text-muted);padding:12px;">No drills in queue.</p>';
        return;
    }
    container.innerHTML = drillQueue.map((d, i) => `
        <div class="drill-queue-item ${currentDrill && currentDrill.id === d.id ? 'active' : ''}" onclick="loadDrill(${i})">
            <span class="drill-queue-name">${d.opening_name || 'Position'} (${d.game_phase || '?'})</span>
            <span class="drill-queue-acc">${d.accuracy != null ? d.accuracy + '%' : 'new'}</span>
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
            const sqClass = isLight ? 'board-square-light' : 'board-square-dark';
            const coordClass = isLight ? 'board-coord-on-light' : 'board-coord-on-dark';
            const piece = board[r][c];
            html += `<div class="board-square ${sqClass}">
                ${piece ? pieces[piece] : ''}
                ${r === 7 ? `<span class="board-coord board-coord-file ${coordClass}">${files[c]}</span>` : ''}
                ${c === 0 ? `<span class="board-coord board-coord-rank ${coordClass}">${ranks[r]}</span>` : ''}
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
                ${result.coaching ? `<div class="summary-notes" style="margin-top:12px;">${formatCoaching(result.coaching)}</div>` : ''}
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

// ── Sessions View ──
let sessionsData = null;

async function loadSessions() {
    try {
        const data = await apiFetch('/api/dashboard/sessions');
        if (data.error) {
            document.getElementById('sess-stop-banner').innerHTML = `
                <span class="sess-stop-label">Sessions</span>
                <div class="sess-stop-detail">${data.error}</div>
            `;
            return;
        }
        sessionsData = data;
        renderSessionsView(data);
    } catch (e) {
        console.error('Failed to load sessions:', e);
    }
}

function renderSessionsView(data) {
    const tilt = data.tilt_detection || {};
    const optimal = data.optimal_session_length || {};

    // Stop point banner
    document.getElementById('sess-stop-banner').innerHTML = `
        <span class="sess-stop-label">Recommended Stop Point</span>
        <div class="sess-stop-value">${tilt.recommended_stop_point || 'Calculating...'}</div>
        <div class="sess-stop-detail">
            ${optimal.crossover_game_count
                ? `Your rating delta turns negative at game ${optimal.crossover_game_count} in a session. Games played beyond this point statistically cost you rating.`
                : 'Keep sessions moderate. Your performance degrades with extended play.'}
        </div>
    `;

    // KPIs
    const optimalNum = optimal.crossover_game_count || '?';
    document.getElementById('sess-kpis').innerHTML = `
        <div class="kpi-card">
            <div class="kpi-value">${data.total_sessions.toLocaleString()}</div>
            <div class="kpi-label">TOTAL SESSIONS</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-value">${data.avg_games_per_session}</div>
            <div class="kpi-label">AVG GAMES / SESSION</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-value ${typeof optimalNum === 'number' ? '' : 'negative'}">${optimalNum}</div>
            <div class="kpi-label">OPTIMAL SESSION LENGTH</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-value negative">${tilt.win_rate_after_2_consecutive_losses ?? '—'}%</div>
            <div class="kpi-label">WR AFTER 2 LOSSES</div>
        </div>
    `;

    // Performance by session length chart
    renderSessionLengthChart(data.performance_by_session_length);

    // Tilt indicator
    renderTiltCard(tilt);

    // Session history table
    renderSessionTable(data.best_sessions, data.worst_sessions);
}

function renderSessionLengthChart(perf) {
    if (!perf || !perf.length) return;

    const canvas = document.getElementById('sess-length-chart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const w = rect.width, h = rect.height;
    const pad = { top: 30, right: 30, bottom: 50, left: 60 };

    ctx.clearRect(0, 0, w, h);

    const deltas = perf.map(p => p.avg_rating_delta);
    const maxAbs = Math.max(Math.abs(Math.min(...deltas)), Math.abs(Math.max(...deltas)), 5) * 1.3;

    const chartW = w - pad.left - pad.right;
    const chartH = h - pad.top - pad.bottom;
    const barW = Math.min(60, chartW / perf.length * 0.6);
    const gap = chartW / perf.length;
    const zeroY = pad.top + chartH / 2;

    // Zero line
    ctx.strokeStyle = 'rgba(255,255,255,0.12)';
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad.left, zeroY);
    ctx.lineTo(w - pad.right, zeroY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Zero label
    ctx.fillStyle = 'rgba(148,163,184,0.5)';
    ctx.font = '10px Inter';
    ctx.textAlign = 'right';
    ctx.fillText('0', pad.left - 8, zeroY + 4);

    perf.forEach((p, i) => {
        const delta = p.avg_rating_delta;
        const x = pad.left + gap * i + (gap - barW) / 2;
        const barH = Math.abs(delta) / maxAbs * (chartH / 2);
        const isPositive = delta >= 0;
        const y = isPositive ? zeroY - barH : zeroY;

        const color = isPositive ? '#00B98E' : '#DB5461';

        // Bar
        const radius = Math.min(4, barW / 2);
        ctx.beginPath();
        if (isPositive) {
            ctx.moveTo(x, y + radius);
            ctx.quadraticCurveTo(x, y, x + radius, y);
            ctx.lineTo(x + barW - radius, y);
            ctx.quadraticCurveTo(x + barW, y, x + barW, y + radius);
            ctx.lineTo(x + barW, zeroY);
            ctx.lineTo(x, zeroY);
        } else {
            ctx.moveTo(x, zeroY);
            ctx.lineTo(x + barW, zeroY);
            ctx.lineTo(x + barW, zeroY + barH - radius);
            ctx.quadraticCurveTo(x + barW, zeroY + barH, x + barW - radius, zeroY + barH);
            ctx.lineTo(x + radius, zeroY + barH);
            ctx.quadraticCurveTo(x, zeroY + barH, x, zeroY + barH - radius);
        }
        ctx.closePath();
        ctx.fillStyle = color;
        ctx.fill();

        // Value label
        ctx.fillStyle = 'rgba(241,245,249,0.9)';
        ctx.font = '600 12px Inter';
        ctx.textAlign = 'center';
        const sign = delta > 0 ? '+' : '';
        const labelY = isPositive ? y - 10 : zeroY + barH + 16;
        ctx.fillText(`${sign}${delta.toFixed(1)}`, x + barW / 2, labelY);

        // Win rate sub-label
        ctx.fillStyle = 'rgba(148,163,184,0.6)';
        ctx.font = '10px Inter';
        ctx.fillText(`${p.win_rate}% WR`, x + barW / 2, labelY + (isPositive ? -14 : 14));

        // Category label
        ctx.fillStyle = 'rgba(148,163,184,0.7)';
        ctx.font = '600 11px Inter';
        ctx.fillText(`${p.games}`, x + barW / 2, h - pad.bottom + 16);
        ctx.fillStyle = 'rgba(148,163,184,0.5)';
        ctx.font = '10px Inter';
        ctx.fillText(`(${p.count})`, x + barW / 2, h - pad.bottom + 30);
    });

    // Y axis label
    ctx.save();
    ctx.fillStyle = 'rgba(148,163,184,0.5)';
    ctx.font = '10px Inter';
    ctx.textAlign = 'center';
    ctx.translate(14, (h - pad.top - pad.bottom) / 2 + pad.top);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Avg Rating Delta', 0, 0);
    ctx.restore();

    // X axis label
    ctx.fillStyle = 'rgba(148,163,184,0.4)';
    ctx.font = '10px Inter';
    ctx.textAlign = 'center';
    ctx.fillText('Games per Session (# sessions)', w / 2, h - 4);
}

function renderTiltCard(tilt) {
    const container = document.getElementById('sess-tilt');
    const wrAfterLoss = tilt.win_rate_after_loss ?? 0;
    const wrAfterWin = tilt.win_rate_after_win ?? 0;
    const wrDrop = (wrAfterWin - wrAfterLoss).toFixed(1);
    const wrAfter2 = tilt.win_rate_after_2_consecutive_losses ?? 0;

    container.innerHTML = `
        <div class="sess-tilt-row">
            <div class="sess-tilt-icon positive">&#9650;</div>
            <div class="sess-tilt-label">Win rate <strong>after a win</strong></div>
            <div class="sess-tilt-value positive">${wrAfterWin}%</div>
        </div>
        <div class="sess-tilt-row">
            <div class="sess-tilt-icon negative">&#9660;</div>
            <div class="sess-tilt-label">Win rate <strong>after a loss</strong>
                <br><span style="font-size:11px;color:var(--color-text-muted);">Drops ${wrDrop} percentage points</span>
            </div>
            <div class="sess-tilt-value negative">${wrAfterLoss}%</div>
        </div>
        <div class="sess-tilt-row">
            <div class="sess-tilt-icon warning">&#9888;</div>
            <div class="sess-tilt-label">Win rate <strong>after 2 consecutive losses</strong>
                <br><span style="font-size:11px;color:var(--color-text-muted);">${tilt.games_after_2_losses || 0} games in this situation</span>
            </div>
            <div class="sess-tilt-value negative">${wrAfter2}%</div>
        </div>
        ${tilt.avg_cpl_after_loss != null ? `
        <div class="sess-tilt-row">
            <div class="sess-tilt-icon negative">&#9733;</div>
            <div class="sess-tilt-label">Avg CPL after a loss vs after a win</div>
            <div class="sess-tilt-value negative">${tilt.avg_cpl_after_loss} vs ${tilt.avg_cpl_after_win}</div>
        </div>` : ''}
    `;
}

function renderSessionTable(best, worst) {
    // Merge best and worst, deduplicate by date, sort by date descending
    const allSessions = [...(best || []), ...(worst || [])];
    const seen = new Set();
    const unique = [];
    for (const s of allSessions) {
        const key = s.date + '_' + s.games;
        if (!seen.has(key)) {
            seen.add(key);
            unique.push(s);
        }
    }
    unique.sort((a, b) => (b.date || '').localeCompare(a.date || ''));

    const tbody = document.getElementById('sess-table-body');
    tbody.innerHTML = unique.map(s => {
        const delta = s.rating_delta ?? 0;
        const deltaClass = delta > 0 ? 'positive' : delta < 0 ? 'negative' : 'neutral';
        const sign = delta > 0 ? '+' : '';
        const resultClass = s.session_result || 'breakeven';

        // Build sparkline from game_ids (use W/L/D indicators)
        const sparkline = buildSparkline(s);

        return `<tr onclick="loadSessionDetail('${s.date}')" style="cursor:pointer;">
            <td>${s.date || '—'}</td>
            <td>${s.games}${sparkline}</td>
            <td>${s.win_count}-${s.loss_count}-${(s.games - s.win_count - s.loss_count)}</td>
            <td><span class="sess-delta-pill ${deltaClass}">${sign}${delta}</span></td>
            <td>${s.longest_loss_streak > 1 ? `<span style="color:#DB5461;font-weight:700;">${s.longest_loss_streak}</span>` : (s.longest_loss_streak || '0')}</td>
            <td><span class="sess-result-badge ${resultClass}">${resultClass.replace('_', ' ')}</span></td>
        </tr>`;
    }).join('');
}

function buildSparkline(session) {
    if (!session.game_ids || session.game_ids.length < 2) return '';
    // We don't have per-game results in the summary data, so show a visual bar proportional to W/L
    const bars = [];
    const w = session.win_count || 0;
    const l = session.loss_count || 0;
    const d = session.games - w - l;
    for (let i = 0; i < w; i++) bars.push('win');
    for (let i = 0; i < d; i++) bars.push('draw');
    for (let i = 0; i < l; i++) bars.push('loss');

    return `<span class="sess-sparkline">${bars.map(t =>
        `<span class="sess-spark-bar ${t}" style="height:${t === 'win' ? '14' : t === 'loss' ? '10' : '6'}px;"></span>`
    ).join('')}</span>`;
}

async function loadSessionDetail(date) {
    const card = document.getElementById('sess-detail-card');
    const detail = document.getElementById('sess-detail');
    card.style.display = 'block';
    detail.innerHTML = '<div class="loading"><div class="spinner"></div>Loading session...</div>';
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    try {
        const data = await apiFetch(`/api/dashboard/sessions/${date}`);
        if (data.error) {
            detail.innerHTML = `<p style="color:var(--color-red);">${data.error}</p>`;
            return;
        }

        let html = `
            <div style="margin-bottom:16px;color:var(--color-text-secondary);font-size:13px;">
                ${data.date} &mdash; ${data.game_count} games &mdash;
                <span class="sess-delta-pill ${data.rating_delta > 0 ? 'positive' : data.rating_delta < 0 ? 'negative' : 'neutral'}">
                    ${data.rating_delta > 0 ? '+' : ''}${data.rating_delta ?? 0}
                </span>
                &mdash; ${data.win_count}W ${data.loss_count}L ${data.draw_count}D
                ${data.longest_loss_streak > 1 ? ` &mdash; <span style="color:#DB5461;">Longest loss streak: ${data.longest_loss_streak}</span>` : ''}
            </div>
        `;

        if (data.games && data.games.length) {
            data.games.forEach((g, i) => {
                const resultClass = g.result === 'win' ? 'positive' : g.result === 'loss' ? 'negative' : '';
                html += `
                    <div class="sess-detail-game">
                        <div class="sess-detail-num">${i + 1}</div>
                        <div class="sess-detail-opening">
                            <span class="badge badge-${g.result}" style="margin-right:8px;">${g.result}</span>
                            ${g.opening_name || 'Unknown'}
                            <span style="color:var(--color-text-muted);font-size:11px;margin-left:6px;">(${g.result_type})</span>
                        </div>
                        <div class="sess-detail-rating">${g.player_rating} vs ${g.opponent_rating}</div>
                        <div style="font-size:12px;color:var(--color-text-muted);">${g.total_moves} moves</div>
                        <div>
                            <button class="btn btn-secondary btn-sm" onclick="openGameReview(${g.game_id})" style="padding:4px 10px;font-size:11px;">Review</button>
                        </div>
                    </div>
                `;
            });
        }

        detail.innerHTML = html;
    } catch (e) {
        detail.innerHTML = `<p style="color:var(--color-red);">Failed to load: ${e.message}</p>`;
    }
}

// ── Opening Book View ──
async function loadOpeningBook() {
    showOpeningList();
    try {
        const data = await apiFetch('/api/dashboard/openings');
        document.getElementById('openingbook-list').innerHTML = data.openings.map(o => `
            <tr onclick="openOpeningDetail('${o.eco}')">
                <td class="td-truncate">${o.opening_name}</td>
                <td>${o.eco || '—'}</td>
                <td>${o.games}</td>
                <td><span class="${o.win_rate > 55 ? 'wr-positive' : o.win_rate < 45 ? 'wr-negative' : 'wr-neutral'}">${o.win_rate}%</span></td>
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
            <h3 class="section-title" style="margin-bottom:12px;">${data.opening_name} <span style="color:var(--color-text-muted);font-weight:500;">(${data.eco})</span></h3>
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
        let movesHtml = '<div style="font-size:13px;line-height:2;">';
        for (const bm of data.book_moves) {
            const isWhite = bm.color === 'white';
            const prefix = isWhite ? `<strong>${bm.move_number}.</strong>` : '';
            const pctClass = bm.main_pct > 70 ? 'pct-bg-high' : bm.main_pct > 40 ? 'pct-bg-mid' : 'pct-bg-low';
            const altText = bm.alternatives.length
                ? `<span class="opening-book-alts">(${bm.alternatives.map(a => `${a.move} ${a.pct}%`).join(', ')})</span>`
                : '';
            movesHtml += `
                <span class="opening-book-move">
                    ${prefix} <span class="notation ${pctClass}">${bm.main_move}</span>
                    <span class="opening-book-pct">${bm.main_pct}%</span>
                    ${altText}
                </span>
            `;
        }
        movesHtml += '</div>';
        document.getElementById('openingbook-moves').innerHTML = movesHtml;

        // Color breakdown
        document.getElementById('openingbook-colors').innerHTML = `
            <div class="color-stats-grid">
                <div class="color-stat-card">
                    <div class="color-stat-icon">&#9812;</div>
                    <div class="color-stat-value">${data.as_white.win_rate}%</div>
                    <div class="color-stat-label">${data.as_white.games} GAMES AS WHITE</div>
                </div>
                <div class="color-stat-card">
                    <div class="color-stat-icon">&#9818;</div>
                    <div class="color-stat-value">${data.as_black.win_rate}%</div>
                    <div class="color-stat-label">${data.as_black.games} GAMES AS BLACK</div>
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
