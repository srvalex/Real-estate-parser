import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#1E1C1A",
        paper: "#F7F4EE",
        "paper-dim": "#EFEAE0",
        brick: "#A8461F",
        "brick-tint": "#A8461F0D",
        pine: "#3E4E3A",
        "pine-tint": "#3E4E3A0D",
        concrete: "#8C8579",
        "concrete-tint": "#8C85791A",
        gold: "#B8892B",
      },
      fontFamily: {
        display: ["var(--font-display)", "ui-serif", "Georgia", "serif"],
        body: ["var(--font-body)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      borderRadius: {
        sm: "4px",
        DEFAULT: "6px",
        md: "6px",
        lg: "8px",
        pill: "999px",
      },
      boxShadow: {
        hover: "0 6px 20px -6px rgba(30, 28, 26, 0.18)",
        card: "none",
      },
      keyframes: {
        "fade-slide-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-slide-up": "fade-slide-up 0.4s ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;
