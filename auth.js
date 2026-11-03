const SESSION_KEY = "dash_session_v1";
const SESSION_MS  = 30 * 60 * 1000;
const LOGIN_PAGE  = "login.html";

function startSession(user) {
  localStorage.setItem(SESSION_KEY, JSON.stringify({
    user, expiresAt: Date.now() + SESSION_MS
  }));
}

function getSession() {
  try {
    const s = JSON.parse(localStorage.getItem(SESSION_KEY));
    if (s && s.expiresAt > Date.now()) return s;
  } catch (e) {}
  localStorage.removeItem(SESSION_KEY);
  return null;
}


function logout() {
  localStorage.removeItem(SESSION_KEY);
  location.replace(LOGIN_PAGE);
}
function requireLogin() {
  if (!getSession()) { location.replace(LOGIN_PAGE); return; }


  setInterval(() => { if (!getSession()) logout(); }, 5000);


  window.addEventListener("storage", e => {
    if (e.key === SESSION_KEY && !e.newValue) location.replace(LOGIN_PAGE);
  });


  window.addEventListener("pageshow", e => {
    if (e.persisted && !getSession()) location.replace(LOGIN_PAGE);
  });
}