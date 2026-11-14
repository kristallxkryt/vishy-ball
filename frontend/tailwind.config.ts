import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0b0e13",
        panel: "#141a22",
        line: "#2a3441",
        muted: "#929cab",
        lime: "#aeb8c5",
      },
      boxShadow: {
        glow: "0 0 80px rgba(174, 184, 197, 0.10)",
      },
    },
  },
  plugins: [],
};

export default config;
