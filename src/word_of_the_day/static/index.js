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
  lookupDate: document.getElementById('lookupDate'),
  lookupBtn: document.getElementById('lookupBtn'),
  historyList: document.getElementById('historyList'),
  errorContainer: document.getElementById('errorContainer'),
  loadingOverlay: document.getElementById('loadingOverlay'),
  speakBtn: document.getElementById('speakBtn'),
  copyBtn: document.getElementById('copyBtn')
};

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
    elements.lookupDate.value = data.date;
    
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
    
    // Highlight in history sidebar
    updateSidebarSelection(date);
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
document.addEventListener('DOMContentLoaded', () => {
  // Init Theme selector
  initThemeSwitcher();
  
  // Pre-load voices for speechSynthesis
  if ('speechSynthesis' in window) {
    window.speechSynthesis.getVoices();
  }

  // Default to today initially as a placeholder
  const todayStr = getLocalDateString();
  elements.lookupDate.value = todayStr;

  // Fetch the most recent historical word to use its date as default
  fetch('/api/history?limit=1')
    .then(response => {
      if (response.ok) {
        return response.json();
      }
      throw new Error('Failed to fetch history');
    })
    .then(async (historyData) => {
      let targetDate = todayStr;
      if (historyData && historyData.length > 0) {
        targetDate = historyData[0].date;
      }
      elements.lookupDate.value = targetDate;
      await loadWord(targetDate);
      loadHistory();
    })
    .catch(async (err) => {
      console.error('Error determining default date, falling back to today:', err);
      elements.lookupDate.value = todayStr;
      await loadWord(todayStr);
      loadHistory();
    });

  // Bind Actions
  if (elements.speakBtn) elements.speakBtn.addEventListener('click', speakWord);
  if (elements.copyBtn) elements.copyBtn.addEventListener('click', copyWordDetails);

  // Bind Lookup button click
  elements.lookupBtn.addEventListener('click', () => {
    const selectedDate = elements.lookupDate.value;
    if (selectedDate) {
      loadWord(selectedDate);
    }
  });

  // Bind Enter key on date input
  elements.lookupDate.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      const selectedDate = elements.lookupDate.value;
      if (selectedDate) {
        loadWord(selectedDate);
      }
    }
  });
});
