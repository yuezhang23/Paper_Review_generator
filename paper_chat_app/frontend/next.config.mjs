/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    /** Main backend (8000): upload, files, get-paper-reviews */
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
    /** Gateway (8010): chat, summary, image, models */
    NEXT_PUBLIC_GATEWAY_URL: process.env.NEXT_PUBLIC_GATEWAY_URL || 'http://localhost:8010',
    NEXT_PUBLIC_USE_GATEWAY: process.env.NEXT_PUBLIC_USE_GATEWAY || '',
  },
}

export default nextConfig
