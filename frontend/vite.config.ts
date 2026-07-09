import path from 'path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), '');
    return {
      define: {
        // This is just generic value for the GEMINI API key.
        // This is not used at all, and can be ignored!
        'process.env.API_KEY' : JSON.stringify('api-key-this-is-not-used-can-be-ignored!'),
      },
      server: {
        proxy: {
          // Vertex AI proxy routes (must be listed BEFORE '/api' so they win the prefix match)
<<<<<<< HEAD
          '/api-proxy': 'http://localhost:5000',
          '/ws-proxy': {target: 'ws://localhost:5000', ws: true},
          // FinSight API: dev traffic goes through Node (:5000) so sessions/auth
          // apply; Node forwards these to the Python/FastAPI service (:8000).
          '/api': 'http://localhost:5000',
          '/extract': 'http://localhost:5000',
          '/ingest-status': 'http://localhost:5000',
          '/market': 'http://localhost:5000',
          '/search': 'http://localhost:5000',
          '/compare-metrics': 'http://localhost:5000',
          '/health': 'http://localhost:5000',
=======
          '/api-proxy': 'http://127.0.0.1:5000',
          '/ws-proxy': {target: 'ws://127.0.0.1:5000', ws: true},
          // FinSight API: dev traffic goes through Node (:5000) so sessions/auth
          // apply; Node forwards these to the Python/FastAPI service (:8000).
          // Use 127.0.0.1 (not localhost) — macOS AirPlay Receiver owns *:5000
          // on IPv6, so 'localhost' resolves to ::1 and hits AirPlay instead of Node.
          '/api': 'http://127.0.0.1:5000',
          '/extract': 'http://127.0.0.1:5000',
          '/ingest-status': 'http://127.0.0.1:5000',
          '/market': 'http://127.0.0.1:5000',
          '/search': 'http://127.0.0.1:5000',
          '/compare-metrics': 'http://127.0.0.1:5000',
          '/health': 'http://127.0.0.1:5000',
>>>>>>> cfd2a823066af4e8a727c06e2762e45bc35843ac
        },
      },
      plugins: react(),
      resolve: {
        alias: {
          '@': path.resolve(__dirname, '.'),
        }
      }
    };
});
