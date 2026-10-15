import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 서버는 /api·/ws를 FastAPI(uvicorn app.main:app, 기본 8000)로 넘긴다. 배포에서는 FastAPI가 dist/를 같은 오리진에서 서빙한다.
// 백엔드 주소를 바꾸려면 PETMINT_API_URL. @fixtures 별칭은 가짜 API 시절의 것 — 지금은 쓰는 곳이 없다
const API = process.env.PETMINT_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@fixtures": path.resolve(__dirname, "../app/fixtures") },
  },
  server: {
    fs: { allow: [path.resolve(__dirname, "..")] },
    proxy: {
      "/api": { target: API, changeOrigin: true },
      "/ws": { target: API.replace(/^http/, "ws"), ws: true, changeOrigin: true },
    },
  },
});
