import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const VENDOR_GROUPS = [
  { name: "charts", test: /node_modules[\\/]lightweight-charts/ },
  { name: "validation", test: /node_modules[\\/](ajv|ajv-formats|json-schema-)[\\/]/ },
  { name: "lodash", test: /node_modules[\\/](lodash[a-z-]*|markdown-to-jsx|nanoid)[\\/]/ },
  { name: "forms", test: /node_modules[\\/]@rjsf/ },
  { name: "antd", test: /node_modules[\\/](antd|@ant-design|rc-)/ },
  { name: "react", test: /node_modules[\\/](react|react-dom|react-router|scheduler)[\\/]/ },
  { name: "data", test: /node_modules[\\/](@tanstack|dayjs)[\\/]/ },
];

export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: VENDOR_GROUPS.map((group) => ({
            name: group.name,
            test: group.test,
          })),
        },
      },
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["**/*.test.*", "src/test/**"],
      thresholds: {
        lines: 80,
        functions: 80,
        branches: 80,
        statements: 80,
      },
    },
  },
});
