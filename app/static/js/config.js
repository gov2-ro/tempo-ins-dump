// Site mode. The FastAPI app serves this file as is ("server": every call goes
// to /api). scripts/build-static.py overwrites it in a static build with
// {"mode": "static", ...}: the same pages then answer from the build's files
// and the browser engine (js/engine/static-api.js).
window.TEMPO_CONFIG = window.TEMPO_CONFIG || { mode: 'server' };
