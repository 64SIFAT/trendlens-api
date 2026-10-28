TRENDLENS API DEPLOYMENT FOR HOSTINGER FRONTEND

Recommended: deploy this folder as a Docker web service on Render. This backend requires Python and is NOT deployable to Hostinger shared Web/Cloud hosting.

1. Put the contents of this folder in a GitHub repository (e.g. trendlens-api).
2. In Render, create a new Web Service from that repo; choose Docker runtime.
3. Set environment variable CORS_ORIGINS=https://trendlens.bytex.my if it is not already set by render.yaml.
4. Deploy. Copy the resulting service URL (e.g. https://trendlens-api.onrender.com).
5. Edit the Hostinger frontend config.js and replace the placeholder API URL with that service URL.
6. Redeploy/re-upload the static frontend to Hostinger.
7. Verify API URL + /api/health returns {"status":"ok"}, then run a regional comparison from the Hostinger website.

Do not claim live analysis is verified until the first POST /api/analyze completes successfully against live data.
