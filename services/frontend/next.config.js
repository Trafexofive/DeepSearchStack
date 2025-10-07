/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  env: {
    DEEPSEARCH_API_URL: process.env.DEEPSEARCH_API_URL || 'http://deepsearch:8001',
  },
}

module.exports = nextConfig
