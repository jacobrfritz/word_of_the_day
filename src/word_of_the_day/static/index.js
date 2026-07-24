// Get YYYY-MM-DD string in local timezone
function getLocalDateString() {
  const d = new Date();
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

// State management
let activeDate = getLocalDateString();
const elements = {
  wordCard: document.getElementById('wordCard'),
  wordDate: document.getElementById('wordDate'),
  wordText: document.getElementById('wordText'),
  wordPos: document.getElementById('wordPos'),
  wordDefinition: document.getElementById('wordDefinition'),
  wordOriginBox: document.getElementById('wordOriginBox'),
  wordOriginText: document.getElementById('wordOriginText'),
  wordSource: document.getElementById('wordSource'),
  wordScore: document.getElementById('wordScore'),
  historyList: document.getElementById('historyList'),
  errorContainer: document.getElementById('errorContainer'),
  loadingOverlay: document.getElementById('loadingOverlay'),
  speakBtn: document.getElementById('speakBtn'),
  copyBtn: document.getElementById('copyBtn'),
  calPrev: document.getElementById('calPrev'),
  calNext: document.getElementById('calNext'),
  calMonthLabel: document.getElementById('calMonthLabel'),
  calendarDays: document.getElementById('calendarDays'),
  calToggle: document.getElementById('calToggle'),
  calTriggerDate: document.getElementById('calTriggerDate'),
  calendarWidget: document.getElementById('calendarWidget'),
  calendarBody: document.getElementById('calendarBody'),
  embeddingCanvas: document.getElementById('embeddingCanvas'),
  embeddingTooltip: document.getElementById('embeddingTooltip'),
  upvoteBtn: document.getElementById('upvoteBtn'),
  downvoteBtn: document.getElementById('downvoteBtn'),
  voteScore: document.getElementById('voteScore'),
};

// ── Embedding space visualization state ──────────────────────────────────────
let embeddingPoints = [];
let hoveredPoint = null;


// ── Calendar State ──────────────────────────────────────────────────────────
let datesWithData = new Set();   // Set of "YYYY-MM-DD" strings
let calViewYear = new Date().getFullYear();
let calViewMonth = new Date().getMonth(); // 0-indexed

// ── Calendar collapse toggle ─────────────────────────────────────────────────
function toggleCalendar(forceOpen) {
  const widget = elements.calendarWidget;
  const toggle = elements.calToggle;
  const isOpen = widget.classList.contains('is-open');
  const shouldOpen = forceOpen !== undefined ? forceOpen : !isOpen;
  widget.classList.toggle('is-open', shouldOpen);
  toggle.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
}

// Update the subtitle date shown on the collapsed trigger
function updateTriggerDate(dateStr) {
  if (!elements.calTriggerDate) return;
  if (!dateStr) { elements.calTriggerDate.textContent = ''; return; }
  const parts = dateStr.split('-');
  const d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
  elements.calTriggerDate.textContent = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

// Helper to format date string nicely
function formatFriendlyDate(dateStr) {
  const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
  const parts = dateStr.split('-');
  const date = new Date(parts[0], parts[1] - 1, parts[2]);
  return date.toLocaleDateString('en-US', options);
}

// Show/hide loader
function setLoader(state) {
  if (!elements.loadingOverlay) return;
  if (state) {
    elements.loadingOverlay.classList.add('active');
  } else {
    elements.loadingOverlay.classList.remove('active');
  }
}

// Fetch and display specific word. Returns true on success, false on failure.
async function loadWord(date) {
  if (!elements.wordCard) return false;
  setLoader(true);
  if (elements.errorContainer) elements.errorContainer.style.display = 'none';
  try {
    const sessionId = getSessionId();
    const response = await fetch(`/wotd/api/word?date=${date}&session_id=${sessionId}`);
    if (!response.ok) {
      throw new Error('Not found');
    }
    const data = await response.json();

    // Update UI
    activeDate = date;
    if (elements.wordDate) elements.wordDate.textContent = formatFriendlyDate(data.date);

    // Parse definition and part of speech
    let wordStr = data.word;
    let defStr = data.definition || 'No definition found.';
    let posStr = 'unknown';

    // Definition format is typically: "(partOfSpeech) Definition text"
    const posMatch = defStr.match(/^\(([^)]+)\)\s*(.*)/);
    if (posMatch) {
      posStr = posMatch[1];
      defStr = posMatch[2];
    }

    if (elements.wordText) elements.wordText.textContent = wordStr;
    if (elements.wordPos) elements.wordPos.textContent = posStr;
    if (elements.wordDefinition) elements.wordDefinition.textContent = defStr;

    if (elements.wordOriginText && elements.wordOriginBox) {
      if (data.origin && data.origin.trim() !== '' && data.origin.trim().toLowerCase() !== 'not available') {
        elements.wordOriginText.textContent = data.origin;
        elements.wordOriginBox.style.display = 'block';
      } else {
        elements.wordOriginText.textContent = 'Not available';
        elements.wordOriginBox.style.display = 'none';
      }
    }

    if (elements.wordSource) elements.wordSource.textContent = data.source;

    // Format Score nicely
    let scoreVal = '-';
    if (data.score !== null && data.score !== undefined) {
      if (data.score > 1.0) {
        scoreVal = `Zipf: ${data.score.toFixed(2)}`;
      } else {
        scoreVal = data.score.toFixed(4);
      }
    } else if (data.extra_info && data.extra_info.zipf_score) {
      scoreVal = `Zipf: ${data.extra_info.zipf_score.toFixed(2)}`;
    }
    if (elements.wordScore) elements.wordScore.textContent = scoreVal;

    // Render voting details
    updateVoteUI(data.upvotes || 0, data.downvotes || 0, data.user_vote);

    // Highlight in history sidebar and calendar
    updateSidebarSelection(date);
    updateTriggerDate(date);
    renderCalendar();
    drawEmbeddingSpace();
    return true;
  } catch (err) {
    if (elements.errorContainer) {
      elements.errorContainer.style.display = 'block';
      elements.errorContainer.textContent = `No Word of the Day was chosen for ${formatFriendlyDate(date)}.`;
    }
    return false;
  } finally {
    setLoader(false);
  }
}

// Fetch and update recent word list
async function loadHistory() {
  if (!elements.historyList) return;
  try {
    const response = await fetch('/wotd/api/history?limit=30');
    if (!response.ok) return;
    const data = await response.json();

    elements.historyList.innerHTML = '';
    if (data.length === 0) {
      elements.historyList.innerHTML = '<div style="color: var(--text-muted); font-size: 0.9rem; text-align: center; padding: 2rem; font-family: monospace;">No history found. Run the generator script!</div>';
      return;
    }

    data.forEach(item => {
      const a = document.createElement('a');
      a.className = `history-item ${item.date === activeDate ? 'active' : ''}`;
      a.href = `/wotd/word/${encodeURIComponent(item.word.toLowerCase())}`;
      a.dataset.date = item.date;

      const parts = item.date.split('-');
      const shortDate = `${parts[1]}/${parts[2]}`; // MM/DD

      a.innerHTML = `
        <span class="hist-word">${item.word}</span>
        <span class="hist-date">${shortDate}</span>
        <span class="hist-details">See Details &rarr;</span>
      `;

      elements.historyList.appendChild(a);
    });
  } catch (err) {
    console.error('Error fetching history:', err);
  }
}

// Fetch all dates that have data from the API
async function loadDatesWithData() {
  try {
    const response = await fetch('/wotd/api/dates');
    if (!response.ok) return;
    const dates = await response.json();
    datesWithData = new Set(dates);
  } catch (err) {
    console.error('Error fetching available dates:', err);
  }
}

// Sync active sidebar item class
function updateSidebarSelection(date) {
  document.querySelectorAll('.history-item').forEach(item => {
    if (item.dataset.date === date) {
      item.classList.add('active');
    } else {
      item.classList.remove('active');
    }
  });
}

// ── Calendar Rendering ──────────────────────────────────────────────────────

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'
];

function renderCalendar() {
  if (!elements.calMonthLabel || !elements.calendarDays) return;

  const year = calViewYear;
  const month = calViewMonth;

  // Update header label
  elements.calMonthLabel.textContent = `${MONTH_NAMES[month]} ${year}`;

  // Days in this month, and what weekday the 1st falls on
  const firstDay = new Date(year, month, 1).getDay(); // 0=Sun
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = getLocalDateString();

  elements.calendarDays.innerHTML = '';

  // Leading empty cells for alignment
  for (let i = 0; i < firstDay; i++) {
    const empty = document.createElement('div');
    empty.className = 'cal-day cal-day--empty';
    elements.calendarDays.appendChild(empty);
  }

  // Day cells
  for (let d = 1; d <= daysInMonth; d++) {
    const mm = String(month + 1).padStart(2, '0');
    const dd = String(d).padStart(2, '0');
    const dateStr = `${year}-${mm}-${dd}`;

    const cell = document.createElement('button');
    cell.className = 'cal-day';
    cell.setAttribute('aria-label', formatFriendlyDate(dateStr));
    cell.type = 'button';

    const numSpan = document.createElement('span');
    numSpan.className = 'cal-day-num';
    numSpan.textContent = d;
    cell.appendChild(numSpan);

    const hasData = datesWithData.has(dateStr);
    const isActive = dateStr === activeDate;
    const isToday = dateStr === today;

    if (hasData) {
      cell.classList.add('cal-day--has-data');
      // Accent dot indicator
      const dot = document.createElement('span');
      dot.className = 'cal-day-dot';
      cell.appendChild(dot);
    }
    if (isToday) cell.classList.add('cal-day--today');
    if (isActive) cell.classList.add('cal-day--active');

    if (hasData) {
      cell.addEventListener('click', () => {
        loadWord(dateStr);
        // Navigate calendar view to follow selection
        calViewYear = year;
        calViewMonth = month;
      });
    } else {
      cell.disabled = true;
      cell.classList.add('cal-day--disabled');
    }

    elements.calendarDays.appendChild(cell);
  }

  // Update prev/next button disabled state
  const minDate = datesWithData.size > 0 ? [...datesWithData].sort()[0] : null;
  const maxDate = datesWithData.size > 0 ? [...datesWithData].sort().at(-1) : null;

  if (minDate && elements.calPrev) {
    const [minY, minM] = minDate.split('-').map(Number);
    elements.calPrev.disabled = (year < minY) || (year === minY && month <= minM - 1);
  }
  if (maxDate && elements.calNext) {
    const [maxY, maxM] = maxDate.split('-').map(Number);
    elements.calNext.disabled = (year > maxY) || (year === maxY && month >= maxM - 1);
  }
}

// Text to speech implementation
function speakWord() {
  if (!elements.wordText) return;
  const word = elements.wordText.textContent;
  if (!word || word === '-') return;

  if ('speechSynthesis' in window) {
    // Cancel any ongoing speech
    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(word);

    // Select a premium English voice if available
    const voices = window.speechSynthesis.getVoices();
    const preferredVoice = voices.find(voice =>
      voice.lang.startsWith('en-') &&
      (voice.name.includes('Google') || voice.name.includes('Natural') || voice.name.includes('Premium'))
    ) || voices.find(voice => voice.lang.startsWith('en'));

    if (preferredVoice) {
      utterance.voice = preferredVoice;
    }

    utterance.rate = 0.9; // Slightly slower for clear pronunciation
    window.speechSynthesis.speak(utterance);
  }
}

// Copy word & definition to clipboard
function copyWordDetails() {
  if (!elements.wordText) return;
  const word = elements.wordText.textContent;
  const pos = elements.wordPos ? elements.wordPos.textContent : '';
  const definition = elements.wordDefinition ? elements.wordDefinition.textContent : '';
  const origin = elements.wordOriginText ? elements.wordOriginText.textContent : '';
  const source = elements.wordSource ? elements.wordSource.textContent : '';

  if (!word || word === '-') return;

  const originStr = origin && origin !== 'Not available' ? `\n\nOrigin:\n${origin}` : '';
  const textToCopy = `Word of the Day: ${word} (${pos})\nDefinition: ${definition}${originStr}\n\nSource: ${source}`;

  navigator.clipboard.writeText(textToCopy).then(() => {
    if (elements.copyBtn) {
      const tooltip = elements.copyBtn.querySelector('.tooltip');
      if (tooltip) {
        tooltip.classList.add('show');
        setTimeout(() => tooltip.classList.remove('show'), 2000);
      }
    }
  }).catch(err => {
    console.error('Clipboard copy failed:', err);
  });
}


function getActiveTheme() {
  return localStorage.getItem('vocabulary-theme') || 'gold';
}

function getClusterColor(clusterId, theme, opacity = 1) {
  let hue = (clusterId * 137.5) % 360;
  let saturation = 60;
  let lightness = 65;

  if (theme === 'nordic') {
    hue = (190 + (clusterId * 40)) % 360;
    saturation = 70;
    lightness = 65;
  } else if (theme === 'forest') {
    hue = (80 + (clusterId * 35)) % 360;
    saturation = 50;
    lightness = 55;
  } else {
    hue = (25 + (clusterId * 45)) % 360;
    saturation = 65;
    lightness = 60;
  }

  return `hsla(${hue}, ${saturation}%, ${lightness}%, ${opacity})`;
}

function drawEmbeddingSpace() {
  const canvas = elements.embeddingCanvas;
  if (!canvas) return;

  const dpr = window.devicePixelRatio || 1;
  const parentRect = canvas.parentElement.getBoundingClientRect();
  const size = Math.floor(parentRect.width);

  // If container is collapsed during initial load, exit early and retry later
  if (size === 0) {
    setTimeout(drawEmbeddingSpace, 100);
    return;
  }

  const targetWidth = Math.floor(size * dpr);
  const targetHeight = Math.floor(size * dpr);

  // Only update attributes if they changed, to avoid resetting context
  if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
  }

  const ctx = canvas.getContext('2d');
  const theme = getActiveTheme();

  // Clear canvas
  ctx.clearRect(0, 0, size, size);

  if (embeddingPoints.length === 0) return;

  const width = size;
  const height = size;
  const padding = 25;

  let activeWord = (elements.wordText && elements.wordText.textContent) ? elements.wordText.textContent.toLowerCase().trim() : '';
  if (!activeWord && activeDate) {
    const matchingPoint = embeddingPoints.find(p => p.date === activeDate);
    if (matchingPoint) {
      activeWord = matchingPoint.word.toLowerCase().trim();
    }
  }
  if (!activeWord && embeddingPoints.length > 0) {
    const sorted = [...embeddingPoints].sort((a, b) => (b.date || '').localeCompare(a.date || ''));
    if (sorted.length > 0) {
      activeWord = sorted[0].word.toLowerCase().trim();
    }
  }

  // Helper function to draw text wrapped in a pill/badge capsule for high legibility
  function drawBadgeLabel(text, x, y, align, baseline, isHighlighted) {
    ctx.save();

    ctx.font = isHighlighted ? '600 11px "Outfit", sans-serif' : '500 10px "JetBrains Mono", monospace';
    const metrics = ctx.measureText(text);
    const textWidth = metrics.width;
    const textHeight = isHighlighted ? 12 : 10;

    const padX = 8;
    const padY = 5;

    // Calculate badge box coordinates
    let bx = x;
    if (align === 'right') {
      bx = x - textWidth - padX * 2;
    } else if (align === 'center') {
      bx = x - textWidth / 2 - padX;
    } else {
      bx = x;
    }

    let by = y;
    if (baseline === 'bottom') {
      by = y - textHeight - padY * 2;
    } else if (baseline === 'top') {
      by = y;
    } else {
      by = y - textHeight / 2 - padY;
    }

    const bw = textWidth + padX * 2;
    const bh = textHeight + padY * 2;

    if (isHighlighted) {
      bx = Math.max(5, Math.min(size - bw - 5, bx));
      by = Math.max(5, Math.min(size - bh - 5, by));
    }

    // Draw badge drop shadow
    ctx.shadowColor = 'rgba(0, 0, 0, 0.4)';
    ctx.shadowBlur = 5;
    ctx.shadowOffsetY = 2;

    // Draw pill background
    ctx.fillStyle = isHighlighted ? 'rgba(18, 18, 22, 0.95)' : 'rgba(24, 24, 28, 0.88)';
    ctx.strokeStyle = isHighlighted ? 'rgba(255, 255, 255, 0.25)' : 'rgba(255, 255, 255, 0.12)';
    ctx.lineWidth = 1;

    ctx.beginPath();
    ctx.roundRect(bx, by, bw, bh, 6);
    ctx.fill();
    ctx.stroke();

    // Reset shadow
    ctx.shadowColor = 'transparent';
    ctx.shadowBlur = 0;
    ctx.shadowOffsetY = 0;

    // Draw text inside the badge
    ctx.fillStyle = isHighlighted ? '#ffffff' : 'rgba(255, 255, 255, 0.85)';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(text, bx + padX, by + padY);

    ctx.restore();

    return { x: bx, y: by, w: bw, h: bh };
  }

  let activePoint = null;

  embeddingPoints.forEach(point => {
    const px = padding + point.x * (width - 2 * padding);
    const py = padding + point.y * (height - 2 * padding);

    point.cx = px;
    point.cy = py;

    const isCurrent = point.word.toLowerCase().trim() === activeWord;
    if (isCurrent) {
      activePoint = point;
      return; // Draw last
    }

    // Draw historical selection dots with larger radius and crisp border
    ctx.beginPath();
    ctx.arc(px, py, 5.5, 0, Math.PI * 2);
    ctx.fillStyle = getClusterColor(point.cluster_id, theme, 0.9);
    ctx.fill();

    ctx.strokeStyle = 'rgba(255, 255, 255, 0.75)';
    ctx.lineWidth = 1.5;
    ctx.stroke();
  });

  if (activePoint) {
    const px = activePoint.cx;
    const py = activePoint.cy;

    // 1. Draw active point highlight rings
    ctx.beginPath();
    ctx.arc(px, py, 13, 0, Math.PI * 2);
    ctx.strokeStyle = getClusterColor(activePoint.cluster_id, theme, 0.3);
    ctx.lineWidth = 5;
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(px, py, 8, 0, Math.PI * 2);
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(px, py, 5.5, 0, Math.PI * 2);
    ctx.fillStyle = getClusterColor(activePoint.cluster_id, theme, 1);
    ctx.fill();
  }

  // 2. Draw hovered point highlight rings (if hoveredPoint is set and is not activePoint)
  if (hoveredPoint && hoveredPoint !== activePoint) {
    const px = hoveredPoint.cx;
    const py = hoveredPoint.cy;

    ctx.beginPath();
    ctx.arc(px, py, 9, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.8)';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(px, py, 5.5, 0, Math.PI * 2);
    ctx.fillStyle = getClusterColor(hoveredPoint.cluster_id, theme, 1);
    ctx.fill();
  }

  // 3. Dynamic Constellation Pop-up on Hover
  const neighborTarget = hoveredPoint;
  if (neighborTarget) {
    const tx = neighborTarget.cx;
    const ty = neighborTarget.cy;

    // Find 3 closest neighbors to the target in projected space
    const neighbors = embeddingPoints
      .filter(p => p.word.toLowerCase().trim() !== neighborTarget.word.toLowerCase().trim())
      .map(p => {
        const dx = p.x - neighborTarget.x;
        const dy = p.y - neighborTarget.y;
        return { point: p, dist2: dx * dx + dy * dy };
      })
      .sort((a, b) => a.dist2 - b.dist2)
      .slice(0, 3)
      .map(n => n.point);

    // Draw thin constellation connection lines to neighbors
    ctx.strokeStyle = getClusterColor(neighborTarget.cluster_id, theme, 0.45);
    ctx.lineWidth = 1.2;
    neighbors.forEach(n => {
      if (n.cx !== undefined && n.cy !== undefined) {
        ctx.beginPath();
        ctx.moveTo(tx, ty);
        ctx.lineTo(n.cx, n.cy);
        ctx.stroke();
      }
    });

    // Draw neighbor labels wrapped in clean dark badges
    neighbors.forEach(n => {
      if (n.cx !== undefined && n.cy !== undefined) {
        drawBadgeLabel(n.word, n.cx + 10, n.cy, 'left', 'middle', false);
      }
    });
  }

  // 4. Always draw active word label badge and thin white line
  if (activePoint) {
    const px = activePoint.cx;
    const py = activePoint.cy;

    const labelAlign = px < size / 2 ? 'left' : 'right';
    const labelBaseline = py < size / 2 ? 'top' : 'bottom';
    const labelX = px < size / 2 ? px + 35 : px - 35;
    const labelY = py < size / 2 ? py + 30 : py - 30;

    const badgeRect = drawBadgeLabel(activePoint.word.toUpperCase(), labelX, labelY, labelAlign, labelBaseline, true);

    // Draw thin white line pointing to active point
    function drawArrow(fromX, fromY, toX, toY, color) {
      const headlen = 6;
      const angle = Math.atan2(toY - fromY, toX - fromX);
      ctx.beginPath();
      ctx.moveTo(fromX, fromY);
      ctx.lineTo(toX, toY);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.2;
      ctx.stroke();

      ctx.beginPath();
      ctx.moveTo(toX, toY);
      ctx.lineTo(toX - headlen * Math.cos(angle - Math.PI / 6), toY - headlen * Math.sin(angle - Math.PI / 6));
      ctx.lineTo(toX - headlen * Math.cos(angle + Math.PI / 6), toY - headlen * Math.sin(angle + Math.PI / 6));
      ctx.fillStyle = color;
      ctx.fill();
    }

    const arrowStartX = Math.max(badgeRect.x, Math.min(badgeRect.x + badgeRect.w, px));
    const arrowStartY = Math.max(badgeRect.y, Math.min(badgeRect.y + badgeRect.h, py));

    const angle = Math.atan2(py - arrowStartY, px - arrowStartX);
    const arrowEndX = px - 9 * Math.cos(angle);
    const arrowEndY = py - 9 * Math.sin(angle);

    drawArrow(arrowStartX, arrowStartY, arrowEndX, arrowEndY, '#ffffff');
  }
}

async function initEmbeddingVisual() {
  const canvas = elements.embeddingCanvas;
  if (!canvas) return;

  function resize() {
    drawEmbeddingSpace();
  }

  resize();
  window.addEventListener('resize', resize);

  try {
    const response = await fetch('/wotd/api/embeddings/grid');
    if (!response.ok) throw new Error('API failed');
    embeddingPoints = await response.json();
    drawEmbeddingSpace();
  } catch (err) {
    console.error('Error fetching embeddings grid:', err);
    return;
  }

  // Helper: Find closest point within threshold
  function getClosestPoint(mx, my, threshold) {
    let closestPoint = null;
    let minDistance = Infinity;

    embeddingPoints.forEach(point => {
      if (point.cx === undefined || point.cy === undefined) return;
      const dx = point.cx - mx;
      const dy = point.cy - my;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < minDistance) {
        minDistance = dist;
        closestPoint = point;
      }
    });

    return minDistance < threshold ? closestPoint : null;
  }

  // Helper: Show/update tooltip
  function updateTooltip(point, mx, my) {
    const tooltip = elements.embeddingTooltip;
    if (!tooltip) return;

    tooltip.style.display = 'block';
    tooltip.style.left = `${mx}px`;
    tooltip.style.top = `${my + 20}px`;

    const dateStr = point.date ? `<div class="tooltip-date">Selected: ${point.date}</div>` : '';
    const sourceName = point.source ? point.source.charAt(0).toUpperCase() + point.source.slice(1) : 'History';

    tooltip.innerHTML = `
      <strong>${point.word}</strong>
      <span>Cluster ${point.cluster_id + 1} (${sourceName})</span>
      ${dateStr}
    `;
  }

  // Helper: Hide tooltip
  function hideTooltip() {
    const tooltip = elements.embeddingTooltip;
    if (tooltip) {
      tooltip.style.display = 'none';
    }
  }

  canvas.addEventListener('mousemove', (e) => {
    if (embeddingPoints.length === 0) return;

    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    const point = getClosestPoint(mx, my, 10);
    if (point) {
      if (hoveredPoint !== point) {
        hoveredPoint = point;
        drawEmbeddingSpace();
      }
      updateTooltip(point, mx, my);
    } else {
      if (hoveredPoint !== null) {
        hoveredPoint = null;
        drawEmbeddingSpace();
        hideTooltip();
      }
    }
  });

  canvas.addEventListener('mouseleave', () => {
    if (hoveredPoint !== null) {
      hoveredPoint = null;
      drawEmbeddingSpace();
    }
    hideTooltip();
  });

  canvas.addEventListener('click', () => {
    if (hoveredPoint) {
      if (hoveredPoint.date) {
        activeDate = hoveredPoint.date;
      }
      if (elements.wordCard) {
        loadWord(hoveredPoint.date);
      } else {
        drawEmbeddingSpace();
      }
    }
  });

  // Touch support for mobile devices
  let touchStartPos = { x: 0, y: 0 };
  let touchStartTime = 0;
  let isTouchActive = false;

  canvas.addEventListener('touchstart', (e) => {
    if (embeddingPoints.length === 0) return;
    isTouchActive = true;
    const rect = canvas.getBoundingClientRect();
    const touch = e.touches[0];
    const mx = touch.clientX - rect.left;
    const my = touch.clientY - rect.top;

    touchStartPos = { x: mx, y: my };
    touchStartTime = Date.now();

    const point = getClosestPoint(mx, my, 20); // Larger threshold for touch
    if (point) {
      hoveredPoint = point;
      drawEmbeddingSpace();
      updateTooltip(point, mx, my);
      e.preventDefault(); // Prevent scrolling when dragging on a point
    }
  }, { passive: false });

  canvas.addEventListener('touchmove', (e) => {
    if (!isTouchActive || embeddingPoints.length === 0) return;
    const rect = canvas.getBoundingClientRect();
    const touch = e.touches[0];
    const mx = touch.clientX - rect.left;
    const my = touch.clientY - rect.top;

    const point = getClosestPoint(mx, my, 20);
    if (point) {
      if (hoveredPoint !== point) {
        hoveredPoint = point;
        drawEmbeddingSpace();
      }
      updateTooltip(point, mx, my);
      e.preventDefault(); // Prevent scrolling when dragging on a point
    } else {
      if (hoveredPoint !== null) {
        hoveredPoint = null;
        drawEmbeddingSpace();
        hideTooltip();
      }
    }
  }, { passive: false });

  canvas.addEventListener('touchend', (e) => {
    isTouchActive = false;
    const duration = Date.now() - touchStartTime;
    const touch = e.changedTouches[0];
    if (!touch) return;
    const rect = canvas.getBoundingClientRect();
    const mx = touch.clientX - rect.left;
    const my = touch.clientY - rect.top;

    const dx = mx - touchStartPos.x;
    const dy = my - touchStartPos.y;
    const dist = Math.sqrt(dx * dx + dy * dy);

    if (dist < 10 && duration < 300) {
      const point = getClosestPoint(mx, my, 20);
      if (point && point.date) {
        loadWord(point.date);
      }
    }
  });
}

// Theme Switcher Initialization
function initThemeSwitcher() {
  const savedTheme = localStorage.getItem('vocabulary-theme') || 'gold';
  setTheme(savedTheme);

  document.querySelectorAll('.theme-dot').forEach(dot => {
    dot.addEventListener('click', () => {
      const theme = dot.dataset.theme;
      setTheme(theme);
    });
  });
}

function setTheme(theme) {
  // Clear previous body theme classes
  document.body.classList.remove('theme-nordic', 'theme-forest');

  // Set theme class on body
  if (theme !== 'gold') {
    document.body.classList.add(`theme-${theme}`);
  }

  // Save preference
  localStorage.setItem('vocabulary-theme', theme);

  // Update active state in UI
  document.querySelectorAll('.theme-dot').forEach(dot => {
    if (dot.dataset.theme === theme) {
      dot.classList.add('active');
    } else {
      dot.classList.remove('active');
    }
  });

  // Redraw embedding space with new theme colors
  drawEmbeddingSpace();
}

// Initialize application events
document.addEventListener('DOMContentLoaded', async () => {
  // Init Theme selector
  initThemeSwitcher();

  // Pre-load voices for speechSynthesis
  if ('speechSynthesis' in window) {
    window.speechSynthesis.getVoices();
  }

  // Load all dates that have data first, then render calendar
  await loadDatesWithData();

  // Fetch the most recent historical word to use its date as default
  let targetDate = getLocalDateString();
  try {
    const response = await fetch('/wotd/api/history?limit=1');
    if (response.ok) {
      const historyData = await response.json();
      if (historyData && historyData.length > 0) {
        targetDate = historyData[0].date;
      }
    }
  } catch (err) {
    console.error('Error determining default date:', err);
  }

  // Navigate calendar to the target date's month
  const parts = targetDate.split('-');
  calViewYear = parseInt(parts[0], 10);
  calViewMonth = parseInt(parts[1], 10) - 1;

  // Render calendar and load the word if components are present
  if (elements.calendarDays && elements.calMonthLabel) {
    renderCalendar();
  }
  if (elements.wordCard) {
    await loadWord(targetDate);
  }
  if (elements.historyList) {
    loadHistory();
  }

  // Bind action buttons
  if (elements.speakBtn) elements.speakBtn.addEventListener('click', speakWord);
  if (elements.copyBtn) elements.copyBtn.addEventListener('click', copyWordDetails);

  // Bind voting buttons
  if (elements.upvoteBtn) {
    elements.upvoteBtn.addEventListener('click', () => castVote('up'));
  }
  if (elements.downvoteBtn) {
    elements.downvoteBtn.addEventListener('click', () => castVote('down'));
  }

  // Populate trigger date label with initially loaded date
  updateTriggerDate(targetDate);

  // Calendar collapse toggle
  if (elements.calToggle) {
    elements.calToggle.addEventListener('click', () => toggleCalendar());
  }

  // Calendar navigation
  if (elements.calPrev) {
    elements.calPrev.addEventListener('click', () => {
      if (calViewMonth === 0) {
        calViewMonth = 11;
        calViewYear--;
      } else {
        calViewMonth--;
      }
      renderCalendar();
    });
  }

  if (elements.calNext) {
    elements.calNext.addEventListener('click', () => {
      if (calViewMonth === 11) {
        calViewMonth = 0;
        calViewYear++;
      } else {
        calViewMonth++;
      }
      renderCalendar();
    });
  }

  // Email Daily Digest Subscription Form Handler
  const subscribeForm = document.getElementById('subscribeForm');
  const subscriberEmail = document.getElementById('subscriberEmail');
  const subscribeSuccess = document.getElementById('subscribeSuccess');
  const subscribeError = document.getElementById('subscribeError');

  if (subscribeForm && subscriberEmail) {
    // Sync ARIA state with validation state
    const syncAria = (el) => {
      const isInvalid = el.matches(':user-invalid') || el.classList.contains('user-invalid-fallback');
      el.setAttribute('aria-invalid', isInvalid ? 'true' : 'false');
    };

    // User-invalid JS Fallback (if :user-invalid isn't supported)
    const initValidationFallback = () => {
      if (window.CSS && window.CSS.supports && window.CSS.supports('selector(:user-invalid)')) return;

      const dirtyState = new WeakMap();

      const updateState = (input) => {
        const isValid = input.checkValidity();
        input.classList.toggle('user-invalid-fallback', !isValid);
        input.classList.toggle('user-valid-fallback', isValid);
        syncAria(input);
      };

      const handleEvent = (event) => {
        const input = event.target;
        if (input !== subscriberEmail) return;

        if (event.type === 'input' || event.type === 'change') {
          const state = dirtyState.get(input) || { hasInteracted: false, hasBlurred: false };
          state.hasInteracted = true;
          dirtyState.set(input, state);
          if (state.hasBlurred) {
            updateState(input);
          }
        } else if (event.type === 'blur') {
          const state = dirtyState.get(input) || { hasInteracted: false, hasBlurred: false };
          state.hasBlurred = true;
          dirtyState.set(input, state);
          if (state.hasInteracted) {
            updateState(input);
          }
        }
      };

      subscribeForm.addEventListener('blur', handleEvent, true);
      subscribeForm.addEventListener('input', handleEvent);
      subscribeForm.addEventListener('change', handleEvent);
    };

    initValidationFallback();

    subscriberEmail.addEventListener('blur', () => syncAria(subscriberEmail));
    subscriberEmail.addEventListener('input', () => {
      subscribeError.style.display = 'none';
      subscriberEmail.classList.remove('user-invalid-fallback');
      subscriberEmail.removeAttribute('aria-invalid');
    });

    subscribeForm.addEventListener('submit', async (e) => {
      e.preventDefault();

      if (!subscribeForm.checkValidity()) {
        subscribeError.style.display = 'block';
        subscribeError.textContent = '❌ Please enter a valid email address.';
        subscriberEmail.setAttribute('aria-invalid', 'true');
        subscriberEmail.classList.add('user-invalid-fallback');
        return;
      }

      const email = subscriberEmail.value.trim();
      const inputGroup = subscribeForm.querySelector('.input-group');

      try {
        const response = await fetch('/wotd/api/subscribe', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ email }),
        });

        const data = await response.json();
        if (response.ok && data.success) {
          subscribeSuccess.style.display = 'block';
          subscribeError.style.display = 'none';
          if (inputGroup) inputGroup.style.display = 'none';
        } else {
          subscribeError.style.display = 'block';
          subscribeError.textContent = `❌ ${data.detail || data.message || 'Subscription failed. Please try again.'}`;
        }
      } catch (err) {
        subscribeError.style.display = 'block';
        subscribeError.textContent = '❌ Network error. Please try again later.';
        console.error('Subscription error:', err);
      }
    });
  }

  // Initialize Embedding Space Visualization
  initEmbeddingVisual();
});


// ── Voting System Helpers ───────────────────────────────────────────────────

function getSessionId() {
  let sessionId = localStorage.getItem('wotd_session_id');
  if (!sessionId) {
    sessionId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      const r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
    localStorage.setItem('wotd_session_id', sessionId);
  }
  return sessionId;
}

function updateVoteUI(upvotes, downvotes, userVote) {
  if (!elements.voteScore || !elements.upvoteBtn || !elements.downvoteBtn) return;
  const netScore = upvotes - downvotes;
  elements.voteScore.textContent = netScore;

  // Style score color
  elements.voteScore.classList.remove('positive', 'negative');
  if (netScore > 0) {
    elements.voteScore.classList.add('positive');
  } else if (netScore < 0) {
    elements.voteScore.classList.add('negative');
  }

  // Toggle active state classes
  elements.upvoteBtn.classList.toggle('active-up', userVote === 1);
  elements.downvoteBtn.classList.toggle('active-down', userVote === -1);
}

async function castVote(direction) {
  if (!activeDate || activeDate === '-') return;

  const sessionId = getSessionId();
  const upvoteBtn = elements.upvoteBtn;
  const downvoteBtn = elements.downvoteBtn;

  // Determine target action (support retracting active vote)
  let targetDirection = direction;
  if (direction === 'up' && upvoteBtn.classList.contains('active-up')) {
    targetDirection = 'clear';
  } else if (direction === 'down' && downvoteBtn.classList.contains('active-down')) {
    targetDirection = 'clear';
  }

  try {
    const response = await fetch('/wotd/api/vote', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        date: activeDate,
        direction: targetDirection,
        session_id: sessionId,
      }),
    });

    if (!response.ok) {
      if (response.status === 429) {
        const errorData = await response.json();
        showToast(errorData.detail || 'Too many votes. Please wait.', 'error');
        return;
      }
      throw new Error('Failed to record vote.');
    }

    const result = await response.json();
    updateVoteUI(result.upvotes, result.downvotes, result.user_vote);
  } catch (err) {
    console.error('Error voting:', err);
    showToast('Failed to record vote. Please check your connection.', 'error');
  }
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${message}</span>`;
  container.appendChild(toast);

  // Trigger CSS transition animation
  setTimeout(() => toast.classList.add('show'), 50);

  // Remove toast automatically
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 400);
  }, 3500);
}
