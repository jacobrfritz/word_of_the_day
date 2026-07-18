// State Management
let token = sessionStorage.getItem('admin_token') || '';
let currentHistory = [];

const elements = {
  loginScreen: document.getElementById('loginScreen'),
  adminDashboard: document.getElementById('adminDashboard'),
  loginForm: document.getElementById('loginForm'),
  adminPasswordInput: document.getElementById('adminPassword'),
  loginError: document.getElementById('loginError'),
  logoutBtn: document.getElementById('logoutBtn'),

  // Tabs
  tabButtons: document.querySelectorAll('.tab-btn'),
  tabPanels: document.querySelectorAll('.tab-panel'),

  // Stats
  statTotalWords: document.getElementById('statTotalWords'),
  statCacheSize: document.getElementById('statCacheSize'),
  statDbSize: document.getElementById('statDbSize'),
  clearCacheBtn: document.getElementById('clearCacheBtn'),
  refreshStatsBtn: document.getElementById('refreshStatsBtn'),
  sendEmailBtn: document.getElementById('sendEmailBtn'),
  sendEmailForce: document.getElementById('sendEmailForce'),
  emailSuccess: document.getElementById('emailSuccess'),
  emailError: document.getElementById('emailError'),

  // Schedule Form
  scheduleForm: document.getElementById('scheduleForm'),
  wordDateInput: document.getElementById('wordDateInput'),
  wordWord: document.getElementById('wordWord'),
  scheduleSuccess: document.getElementById('scheduleSuccess'),
  historyTableBody: document.getElementById('historyTableBody'),

  // Explorer
  exploreForm: document.getElementById('exploreForm'),
  exploreMinLength: document.getElementById('exploreMinLength'),
  exploreMaxLength: document.getElementById('exploreMaxLength'),
  explorePosNouns: document.getElementById('explorePosNouns'),
  explorePosAdjectives: document.getElementById('explorePosAdjectives'),
  explorePosVerbs: document.getElementById('explorePosVerbs'),
  exploreLimit: document.getElementById('exploreLimit'),
  exploreEmbeddings: document.getElementById('exploreEmbeddings'),
  explorerSpinner: document.getElementById('explorerSpinner'),
  explorerResultsList: document.getElementById('explorerResultsList'),

  // Logs
  logsLineCount: document.getElementById('logsLineCount'),
  refreshLogsBtn: document.getElementById('refreshLogsBtn'),
  logsTerminalBody: document.getElementById('logsTerminalBody'),
};

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
  initThemeSwitcher();
  setupAuthentication();
  setupTabs();
  setupEventListeners();

  // Set default date in form to today
  if (elements.wordDateInput) {
    const today = new Date().toISOString().split('T')[0];
    elements.wordDateInput.value = today;
  }
});

// --- Theme Switcher ---
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
  document.body.classList.remove('theme-nordic', 'theme-forest');
  if (theme !== 'gold') {
    document.body.classList.add(`theme-${theme}`);
  }
  localStorage.setItem('vocabulary-theme', theme);
  document.querySelectorAll('.theme-dot').forEach(dot => {
    if (dot.dataset.theme === theme) {
      dot.classList.add('active');
    } else {
      dot.classList.remove('active');
    }
  });
}

// --- Authentication UI Flow ---
function setupAuthentication() {
  if (token) {
    showDashboard();
  } else {
    showLogin();
  }

  elements.loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const password = elements.adminPasswordInput.value;

    try {
      const response = await fetch('/api/admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password })
      });

      if (!response.ok) {
        throw new Error('Authentication failed');
      }

      const data = await response.json();
      token = data.token;
      sessionStorage.setItem('admin_token', token);
      elements.loginError.style.display = 'none';
      elements.adminPasswordInput.value = '';
      showDashboard();
    } catch (err) {
      elements.loginError.style.display = 'block';
      elements.loginError.textContent = 'Invalid credentials. Access denied.';
    }
  });

  elements.logoutBtn.addEventListener('click', () => {
    token = '';
    sessionStorage.removeItem('admin_token');
    showLogin();
  });
}

function showLogin() {
  elements.loginScreen.style.display = 'block';
  elements.adminDashboard.style.display = 'none';
}

function showDashboard() {
  elements.loginScreen.style.display = 'none';
  elements.adminDashboard.style.display = 'block';

  // Load initial active tab data
  const activeTabBtn = document.querySelector('.tab-btn.active');
  if (activeTabBtn) {
    loadTabContent(activeTabBtn.dataset.tab);
  }
}

// --- Tabs Management ---
function setupTabs() {
  elements.tabButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      elements.tabButtons.forEach(b => b.classList.remove('active'));
      elements.tabPanels.forEach(p => p.classList.remove('active'));

      btn.classList.add('active');
      const targetPanel = document.getElementById(btn.dataset.tab);
      if (targetPanel) {
        targetPanel.classList.add('active');
        loadTabContent(btn.dataset.tab);
      }
    });
  });
}

function loadTabContent(tabId) {
  if (tabId === 'statsTab') {
    loadMetrics();
  } else if (tabId === 'scheduleTab') {
    loadHistory();
  } else if (tabId === 'logsTab') {
    loadLogs();
  }
}

// --- API Helpers ---
async function fetchAdmin(url, options = {}) {
  options.headers = {
    ...options.headers,
    'Authorization': `Bearer ${token}`
  };

  const response = await fetch(url, options);
  if (response.status === 401) {
    // Session expired or invalid token
    token = '';
    sessionStorage.removeItem('admin_token');
    showLogin();
    throw new Error('Unauthorized');
  }
  return response;
}

// --- Overview / Stats Tab ---
async function loadMetrics() {
  try {
    const response = await fetchAdmin('/api/admin/stats');
    if (!response.ok) throw new Error('Failed to load metrics');
    const data = await response.json();

    elements.statTotalWords.textContent = data.total_words;
    elements.statCacheSize.textContent = data.cache_size;

    // Format database size
    const mb = data.db_size_bytes / (1024 * 1024);
    elements.statDbSize.textContent = `${mb.toFixed(2)} MB`;
  } catch (err) {
    console.error(err);
  }
}

// --- Schedule / Edit Word Tab ---
async function loadHistory() {
  try {
    const response = await fetchAdmin('/api/admin/history');
    if (!response.ok) throw new Error('Failed to load history');
    currentHistory = await response.json();

    const tbody = elements.historyTableBody;
    tbody.innerHTML = '';

    if (currentHistory.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-center">No history recorded yet.</td></tr>';
      return;
    }

    currentHistory.forEach(record => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="cell-date font-mono">${record.date}</td>
        <td class="cell-word font-accent"><strong>${record.word.toUpperCase()}</strong></td>
        <td><span class="badge-source">${record.source}</span></td>
        <td class="cell-def">${record.definition}</td>
        <td>
          <div class="table-actions">
            <button class="action-btn-danger btn-sm delete-word-btn" data-date="${record.date}">Delete</button>
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    });

    // Bind delete buttons
    document.querySelectorAll('.delete-word-btn').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const date = e.target.dataset.date;
        if (confirm(`Are you sure you want to delete the Word of the Day entry for ${date}?`)) {
          await deleteWord(date);
        }
      });
    });

  } catch (err) {
    elements.historyTableBody.innerHTML = `<tr><td colspan="5" class="text-center text-danger">Error loading history: ${err.message}</td></tr>`;
  }
}

async function deleteWord(date) {
  try {
    const response = await fetchAdmin(`/api/admin/word?date=${date}`, {
      method: 'DELETE'
    });
    if (!response.ok) throw new Error('Failed to delete word');

    // Success notification and refresh
    showFlashMessage('scheduleSuccess', 'Word selection deleted successfully!');
    loadHistory();
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
}

// --- Candidate Explorer Tab ---
async function handleExplore(e) {
  e.preventDefault();

  // Show spinner
  elements.explorerSpinner.style.display = 'flex';
  elements.explorerResultsList.innerHTML = '';

  const sourcesCheckboxes = document.querySelectorAll('input[name="exploreSources"]:checked');
  const sources = Array.from(sourcesCheckboxes).map(cb => cb.value);

  if (sources.length === 0) {
    elements.explorerSpinner.style.display = 'none';
    elements.explorerResultsList.innerHTML = '<p class="text-center text-danger">Please select at least one source.</p>';
    return;
  }

  const payload = {
    sources,
    limit: parseInt(elements.exploreLimit.value, 10),
    use_embeddings: elements.exploreEmbeddings.value === 'true',
    min_word_length: elements.exploreMinLength.value ? parseInt(elements.exploreMinLength.value, 10) : null,
    max_word_length: elements.exploreMaxLength.value ? parseInt(elements.exploreMaxLength.value, 10) : null,
    pos_filter_nouns: elements.explorePosNouns.checked,
    pos_filter_adjectives: elements.explorePosAdjectives.checked,
    pos_filter_verbs: elements.explorePosVerbs.checked
  };

  try {
    const response = await fetchAdmin('/api/admin/explore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!response.ok) throw new Error('Extraction pipeline failed');
    const data = await response.json();

    const candidates = data.candidates;
    elements.explorerSpinner.style.display = 'none';

    if (!candidates || candidates.length === 0) {
      elements.explorerResultsList.innerHTML = '<p class="text-center text-muted">No eligible reusable words found in the harvested text.</p>';
      return;
    }

    candidates.forEach(cand => {
      const card = document.createElement('div');
      card.className = 'candidate-card glass-card';

      const scoreLabel = cand.score ? `Score: ${cand.score.toFixed(4)}` : '';
      const badgeSuffix = scoreLabel ? ` (${scoreLabel})` : '';

      card.innerHTML = `
        <div class="candidate-header">
          <div class="candidate-title-group">
            <h3 class="candidate-word">${cand.word.toUpperCase()}</h3>
            <span class="candidate-meta">${cand.source}${badgeSuffix}</span>
          </div>
          <button class="action-btn select-candidate-btn"
            data-word="${cand.word}"
            data-definition="${cand.definition}"
            data-origin="${cand.origin || ''}"
            data-source="${cand.source}">
            Use & Schedule
          </button>
        </div>
        <p class="candidate-definition">${cand.definition}</p>
        ${cand.origin ? `<p class="candidate-origin"><strong>Etymology:</strong> ${cand.origin}</p>` : ''}
      `;
      elements.explorerResultsList.appendChild(card);
    });

    // Bind schedule from candidate click
    document.querySelectorAll('.select-candidate-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const ds = e.target.dataset;
        const targetDate = prompt('Enter date to schedule this word (YYYY-MM-DD):', new Date().toISOString().split('T')[0]);
        if (targetDate) {
          scheduleWordFromCandidate(targetDate, ds.word, ds.definition, ds.origin, ds.source);
        }
      });
    });

  } catch (err) {
    elements.explorerSpinner.style.display = 'none';
    elements.explorerResultsList.innerHTML = `<p class="text-center text-danger">Pipeline Error: ${err.message}</p>`;
  }
}

async function scheduleWordFromCandidate(date, word, definition, origin, source) {
  try {
    const response = await fetchAdmin('/api/admin/word', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        date,
        word,
        definition,
        source,
        origin: origin || null
      })
    });

    if (!response.ok) {
      const errData = await response.json();
      throw new Error(errData.detail || 'Failed to save');
    }

    // Direct transition to Schedule tab to see the update
    const scheduleTabBtn = document.querySelector('[data-tab="scheduleTab"]');
    scheduleTabBtn.click();
    showFlashMessage('scheduleSuccess', `Scheduled word '${word.toUpperCase()}' successfully for ${date}!`);
  } catch (err) {
    alert(`Error scheduling: ${err.message}`);
  }
}

// --- Live Logs Tab ---
async function loadLogs() {
  try {
    const lines = elements.logsLineCount.value;
    const response = await fetchAdmin(`/api/admin/logs?lines=${lines}`);
    if (!response.ok) throw new Error('Failed to retrieve logs');
    const data = await response.json();

    const terminal = elements.logsTerminalBody;
    if (data.logs.length === 0) {
      terminal.textContent = 'Runtime log file is empty or not found.';
      return;
    }

    terminal.textContent = data.logs.join('\n');
    // Scroll terminal to bottom
    terminal.scrollTop = terminal.scrollHeight;
  } catch (err) {
    elements.logsTerminalBody.textContent = `Error fetching logs: ${err.message}`;
  }
}

// --- Event Listeners and Helpers ---
function setupEventListeners() {
  // Stats
  elements.refreshStatsBtn.addEventListener('click', loadMetrics);

  elements.clearCacheBtn.addEventListener('click', async () => {
    if (confirm('Are you sure you want to purge the definition lookup cache? This will cause the pipeline to run slower next time as it re-queries Merriam-Webster.')) {
      try {
        const response = await fetchAdmin('/api/admin/cache/clear', { method: 'POST' });
        if (response.ok) {
          alert('Dictionary cache cleared successfully.');
          loadMetrics();
        }
      } catch (err) {
        alert(`Error: ${err.message}`);
      }
    }
  });

  // Email Dispatch
  if (elements.sendEmailBtn) {
    elements.sendEmailBtn.addEventListener('click', async () => {
      const force = elements.sendEmailForce ? elements.sendEmailForce.checked : false;
      let confirmMsg = "Are you sure you want to send today's Word of the Day email to all active subscribers?";
      if (force) {
        confirmMsg += "\n\n(This will bypass the duplicate check and send it again to everyone)";
      }

      if (confirm(confirmMsg)) {
        elements.sendEmailBtn.disabled = true;
        const originalText = elements.sendEmailBtn.textContent;
        elements.sendEmailBtn.textContent = 'Sending...';
        if (elements.emailSuccess) elements.emailSuccess.style.display = 'none';
        if (elements.emailError) elements.emailError.style.display = 'none';

        try {
          const response = await fetchAdmin('/api/admin/send-email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force })
          });

          const data = await response.json();

          if (!response.ok) {
            throw new Error(data.detail || 'Failed to send emails');
          }

          if (elements.emailSuccess) {
            elements.emailSuccess.textContent = data.message;
            elements.emailSuccess.style.display = 'block';
            setTimeout(() => {
              elements.emailSuccess.style.display = 'none';
            }, 6000);
          }
        } catch (err) {
          if (elements.emailError) {
            elements.emailError.textContent = `Error: ${err.message}`;
            elements.emailError.style.display = 'block';
          }
        } finally {
          elements.sendEmailBtn.disabled = false;
          elements.sendEmailBtn.textContent = originalText;
        }
      }
    });
  }

  // Custom Form Submission
  elements.scheduleForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      date: elements.wordDateInput.value,
      word: elements.wordWord.value
    };

    try {
      const response = await fetchAdmin('/api/admin/word', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Failed to save');
      }

      showFlashMessage('scheduleSuccess', 'Word of the Day scheduled successfully!');

      // Reset form (except date)
      elements.wordWord.value = '';

      loadHistory();
    } catch (err) {
      alert(`Error scheduling: ${err.message}`);
    }
  });

  // Explorer form
  elements.exploreForm.addEventListener('submit', handleExplore);

  // Logs buttons
  elements.refreshLogsBtn.addEventListener('click', loadLogs);
  elements.logsLineCount.addEventListener('change', loadLogs);
}

function showFlashMessage(elementId, message) {
  const el = document.getElementById(elementId);
  if (!el) return;
  el.textContent = message;
  el.style.display = 'block';
  setTimeout(() => {
    el.style.display = 'none';
  }, 4000);
}
