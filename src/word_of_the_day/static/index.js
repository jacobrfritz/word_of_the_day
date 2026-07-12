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
  loadingOverlay: document.getElementById('loadingOverlay')
};

// Helper to format date string nicely
function formatFriendlyDate(dateStr) {
  const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
  // Parse local timezone date correctly to avoid offset errors
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
    
    if (data.origin) {
      elements.wordOriginText.textContent = data.origin;
      elements.wordOriginBox.style.display = 'block';
    } else {
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
    // Keep active fields as-is, just clear loader
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
      elements.historyList.innerHTML = '<div style="color: var(--text-muted); font-size: 0.9rem; text-align: center; padding: 1rem;">No history found yet. Run the selector script!</div>';
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

// Initialize application events
document.addEventListener('DOMContentLoaded', () => {
  // Set default input date to today
  const todayStr = getLocalDateString();
  elements.lookupDate.value = todayStr;
  
  // Load today's word, fallback to most recent if not found
  loadWord(todayStr).then(async (success) => {
    if (!success) {
      try {
        const historyResponse = await fetch('/api/history?limit=1');
        if (historyResponse.ok) {
          const historyData = await historyResponse.json();
          if (historyData && historyData.length > 0) {
            // Clear the error message since we are showing the latest historical word
            elements.errorContainer.style.display = 'none';
            await loadWord(historyData[0].date);
          }
        }
      } catch (historyErr) {
        console.error('Failed to load fallback historical word:', historyErr);
      }
    }
    loadHistory();
  });

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
