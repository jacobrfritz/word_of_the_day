// State & elements setup
const elements = {
  speakBtn: document.getElementById('speakBtn'),
  copyBtn: document.getElementById('copyBtn'),
  upvoteBtn: document.getElementById('upvoteBtn'),
  downvoteBtn: document.getElementById('downvoteBtn'),
  voteScore: document.getElementById('voteScore'),
  wordText: document.getElementById('wordText'),
};

// --- Theme Management ---
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

// --- Clipboard Copy ---
function copyWordDetails() {
  const word = pageData.word;
  const definition = pageData.definition;
  const origin = pageData.origin;
  const source = pageData.source;

  if (!word) return;

  const originStr = origin && origin !== 'Not available' ? `\n\nOrigin:\n${origin}` : '';
  const textToCopy = `Word of the Day: ${word}\nDefinition: ${definition}${originStr}\n\nSource: ${source}`;

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

// --- Text-to-Speech ---
function speakWord() {
  const word = pageData.word;
  if (!word) return;

  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(word);
    const voices = window.speechSynthesis.getVoices();
    const preferredVoice = voices.find(voice =>
      voice.lang.startsWith('en-') &&
      (voice.name.includes('Google') || voice.name.includes('Natural') || voice.name.includes('Premium'))
    ) || voices.find(voice => voice.lang.startsWith('en'));

    if (preferredVoice) {
      utterance.voice = preferredVoice;
    }
    utterance.rate = 0.9;
    window.speechSynthesis.speak(utterance);
  }
}

// --- Session & Voting ---
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

  elements.voteScore.classList.remove('positive', 'negative');
  if (netScore > 0) {
    elements.voteScore.classList.add('positive');
  } else if (netScore < 0) {
    elements.voteScore.classList.add('negative');
  }

  elements.upvoteBtn.classList.toggle('active-up', userVote === 1);
  elements.downvoteBtn.classList.toggle('active-down', userVote === -1);
}

async function fetchInitialVoteState() {
  if (!pageData.word) return;
  const sessionId = getSessionId();
  try {
    const queryParam = pageData.date ? `date=${encodeURIComponent(pageData.date)}` : `word=${encodeURIComponent(pageData.word)}`;
    const response = await fetch(`/wotd/api/word?${queryParam}&session_id=${sessionId}`);
    if (response.ok) {
      const data = await response.json();
      updateVoteUI(data.upvotes || 0, data.downvotes || 0, data.user_vote);
    }
  } catch (err) {
    console.error('Error fetching initial vote state:', err);
  }
}

async function castVote(direction) {
  if (!pageData.word) return;

  const sessionId = getSessionId();
  const upvoteBtn = elements.upvoteBtn;
  const downvoteBtn = elements.downvoteBtn;

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
        word: pageData.word,
        date: pageData.date || '',
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
    showToast('Failed to record vote. Please check connection.', 'error');
  }
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => toast.classList.add('show'), 50);

  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 400);
  }, 3500);
}

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
  initThemeSwitcher();

  if ('speechSynthesis' in window) {
    window.speechSynthesis.getVoices();
  }

  if (elements.speakBtn) elements.speakBtn.addEventListener('click', speakWord);
  if (elements.copyBtn) elements.copyBtn.addEventListener('click', copyWordDetails);

  if (elements.upvoteBtn) {
    elements.upvoteBtn.addEventListener('click', () => castVote('up'));
  }
  if (elements.downvoteBtn) {
    elements.downvoteBtn.addEventListener('click', () => castVote('down'));
  }

  fetchInitialVoteState();
});
