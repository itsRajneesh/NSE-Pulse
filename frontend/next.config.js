/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false,
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'https://nse-pulse-backend.onrender.com/api/:path*',
      },
    ];
  },
};

module.exports = nextConfig;
