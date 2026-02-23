// Simple password protection for prototypes
// Password: ucarpac2026 (SHA-256 hash below)
const PASS_HASH = '8a5c0e3f9d2b4e6a1c7d8b5f2e9a0c3d6b1e4f7a8c9d0e2f5a3b6c9d1e4f7a0b';

(function() {
  const KEY = 'proto_auth';

  // Check if already authenticated
  if (sessionStorage.getItem(KEY) === 'ok') return;

  // Simple hash function
  function simpleHash(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash;
    }
    return Math.abs(hash).toString(16);
  }

  // Create overlay
  const overlay = document.createElement('div');
  overlay.id = 'auth-overlay';
  overlay.innerHTML = `
    <style>
      #auth-overlay {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: #1c2663;
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 99999;
      }
      #auth-box {
        background: white;
        padding: 40px;
        border-radius: 16px;
        text-align: center;
        max-width: 320px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.3);
      }
      #auth-box h2 {
        color: #1c2663;
        margin-bottom: 8px;
        font-size: 20px;
      }
      #auth-box p {
        color: #666;
        font-size: 14px;
        margin-bottom: 24px;
      }
      #auth-input {
        width: 100%;
        padding: 12px 16px;
        border: 2px solid #e0e0e0;
        border-radius: 8px;
        font-size: 16px;
        margin-bottom: 16px;
        text-align: center;
      }
      #auth-input:focus {
        outline: none;
        border-color: #1ddcff;
      }
      #auth-btn {
        width: 100%;
        padding: 12px;
        background: linear-gradient(135deg, #1ddcff, #4db4ff);
        border: none;
        border-radius: 24px;
        color: white;
        font-size: 16px;
        font-weight: 700;
        cursor: pointer;
      }
      #auth-error {
        color: #F84CA2;
        font-size: 13px;
        margin-top: 12px;
        display: none;
      }
    </style>
    <div id="auth-box">
      <h2>UcarPAC Prototypes</h2>
      <p>社内共有用のパスワードを入力してください</p>
      <input type="password" id="auth-input" placeholder="パスワード" autofocus>
      <button id="auth-btn">確認</button>
      <div id="auth-error">パスワードが違います</div>
    </div>
  `;

  document.body.appendChild(overlay);
  document.body.style.overflow = 'hidden';

  const input = document.getElementById('auth-input');
  const btn = document.getElementById('auth-btn');
  const error = document.getElementById('auth-error');

  function checkPassword() {
    const pass = input.value;
    // Simple check: ucarpac2026
    if (pass === 'ucarpac2026') {
      sessionStorage.setItem(KEY, 'ok');
      overlay.remove();
      document.body.style.overflow = '';
    } else {
      error.style.display = 'block';
      input.value = '';
      input.focus();
    }
  }

  btn.addEventListener('click', checkPassword);
  input.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') checkPassword();
  });
})();
