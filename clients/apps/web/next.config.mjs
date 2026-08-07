/** @type {import('next').NextConfig} */
export default {
  // packages/* ship TypeScript source; Next compiles them in the app build.
  transpilePackages: ["@techtrend/core", "@techtrend/api-client"],
  reactStrictMode: true,
};
