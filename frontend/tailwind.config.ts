import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0b0f0e",
        panel: "#121917",
        line: "#26312d",
        muted: "#8b9992",
        lime: "#c5f36b",
      },
      boxShadow: {
        glow: "0 0 80px rgba(197, 243, 107, 0.12)",
      },
    },
  },
  plugins: [],
};

export default config;
