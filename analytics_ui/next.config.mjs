/** @type {import('next').NextConfig} */
const nextConfig = {
  // No remote images: this dashboard renders aggregates only, never a
  // listing photo. Nothing to configure, and nothing that could pull a
  // listing-level asset in by accident.
};

export default nextConfig;
