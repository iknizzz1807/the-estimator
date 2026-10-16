import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Single-service deploy: FastAPI serves the statically-exported frontend
  // from frontend/out on the same port as /api/* (see backend/app/main.py).
  output: "export",
  // A static file server has no image optimizer.
  images: { unoptimized: true },
  // trailingSlash stays at the default (false): pages are exported as
  // out/estimate.html etc., which the backend resolves from /estimate.
};

export default nextConfig;
