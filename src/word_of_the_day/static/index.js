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
};

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
  if (state) {
    elements.loadingOverlay.classList.add('active');
  } else {
    elements.loadingOverlay.classList.remove('active');
  }
}

// Fetch and display specific word. Returns true on success, false on failure.
async function loadWord(date) {
  setLoader(true);
  elements.errorContainer.style.display = 'none';
  try {
    const response = await fetch(`/api/word?date=${date}`);
    if (!response.ok) {
      throw new Error('Not found');
    }
    const data = await response.json();
    
    // Update UI
    activeDate = date;
    elements.wordDate.textContent = formatFriendlyDate(data.date);
    
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
    
    elements.wordText.textContent = wordStr;
    elements.wordPos.textContent = posStr;
    elements.wordDefinition.textContent = defStr;
    
    if (data.origin && data.origin.trim() !== '' && data.origin.trim().toLowerCase() !== 'not available') {
      elements.wordOriginText.textContent = data.origin;
      elements.wordOriginBox.style.display = 'block';
    } else {
      elements.wordOriginText.textContent = 'Not available';
      elements.wordOriginBox.style.display = 'none';
    }
    
    elements.wordSource.textContent = data.source;
    
    // Format Score nicely
    let scoreVal = '-';
    if (data.score !== null && data.score !== undefined) {
      scoreVal = data.score.toFixed(4);
    } else if (data.extra_info && data.extra_info.zipf_score) {
      scoreVal = `Zipf: ${data.extra_info.zipf_score.toFixed(2)}`;
    }
    elements.wordScore.textContent = scoreVal;
    
    // Highlight in history sidebar and calendar
    updateSidebarSelection(date);
    updateTriggerDate(date);
    renderCalendar();
    return true;
  } catch (err) {
    elements.errorContainer.style.display = 'block';
    elements.errorContainer.textContent = `No Word of the Day was chosen for ${formatFriendlyDate(date)}.`;
    return false;
  } finally {
    setLoader(false);
  }
}

// Fetch and update recent word list
async function loadHistory() {
  try {
    const response = await fetch('/api/history?limit=30');
    if (!response.ok) return;
    const data = await response.json();
    
    elements.historyList.innerHTML = '';
    if (data.length === 0) {
      elements.historyList.innerHTML = '<div style="color: var(--text-muted); font-size: 0.9rem; text-align: center; padding: 2rem; font-family: monospace;">No history found. Run the generator script!</div>';
      return;
    }
    
    data.forEach(item => {
      const div = document.createElement('div');
      div.className = `history-item ${item.date === activeDate ? 'active' : ''}`;
      div.dataset.date = item.date;
      
      const parts = item.date.split('-');
      const shortDate = `${parts[1]}/${parts[2]}`; // MM/DD
      
      div.innerHTML = `
        <span class="hist-word">${item.word}</span>
        <span class="hist-date">${shortDate}</span>
      `;
      
      div.addEventListener('click', () => {
        loadWord(item.date);
      });
      
      elements.historyList.appendChild(div);
    });
  } catch (err) {
    console.error('Error fetching history:', err);
  }
}

// Fetch all dates that have data from the API
async function loadDatesWithData() {
  try {
    const response = await fetch('/api/dates');
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

  if (minDate) {
    const [minY, minM] = minDate.split('-').map(Number);
    elements.calPrev.disabled = (year < minY) || (year === minY && month <= minM - 1);
  }
  if (maxDate) {
    const [maxY, maxM] = maxDate.split('-').map(Number);
    elements.calNext.disabled = (year > maxY) || (year === maxY && month >= maxM - 1);
  }
}

// Text to speech implementation
function speakWord() {
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
  const word = elements.wordText.textContent;
  const pos = elements.wordPos.textContent;
  const definition = elements.wordDefinition.textContent;
  const origin = elements.wordOriginText.textContent;
  const source = elements.wordSource.textContent;
  
  if (!word || word === '-') return;
  
  const originStr = origin && origin !== 'Not available' ? `\n\nOrigin:\n${origin}` : '';
  const textToCopy = `Word of the Day: ${word} (${pos})\nDefinition: ${definition}${originStr}\n\nSource: ${source}`;
  
  navigator.clipboard.writeText(textToCopy).then(() => {
    const tooltip = elements.copyBtn.querySelector('.tooltip');
    if (tooltip) {
      tooltip.classList.add('show');
      setTimeout(() => tooltip.classList.remove('show'), 2000);
    }
  }).catch(err => {
    console.error('Clipboard copy failed:', err);
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
    const response = await fetch('/api/history?limit=1');
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

  // Render calendar and load the word
  renderCalendar();
  await loadWord(targetDate);
  loadHistory();

  // Bind action buttons
  if (elements.speakBtn) elements.speakBtn.addEventListener('click', speakWord);
  if (elements.copyBtn) elements.copyBtn.addEventListener('click', copyWordDetails);

  // Populate trigger date label with initially loaded date
  updateTriggerDate(targetDate);

  // Calendar collapse toggle
  if (elements.calToggle) {
    elements.calToggle.addEventListener('click', () => toggleCalendar());
  }

  // Calendar navigation
  elements.calPrev.addEventListener('click', () => {
    if (calViewMonth === 0) {
      calViewMonth = 11;
      calViewYear--;
    } else {
      calViewMonth--;
    }
    renderCalendar();
  });

  elements.calNext.addEventListener('click', () => {
    if (calViewMonth === 11) {
      calViewMonth = 0;
      calViewYear++;
    } else {
      calViewMonth++;
    }
    renderCalendar();
  });
});
