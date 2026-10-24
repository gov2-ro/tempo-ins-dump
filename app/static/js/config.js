// Site mode. The FastAPI app serves this file as is ("server": every call goes
// to /api). scripts/build-static.py overwrites it in a static build with
// {"mode": "static", ...}: the same pages then answer from the build's files
// and the browser engine (js/engine/static-api.js). `api_origin` (static build
// --api-origin) names the API host that serves Ask to pages served elsewhere.
window.TEMPO_CONFIG = window.TEMPO_CONFIG || { mode: 'server' };
