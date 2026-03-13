import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#f7f1e7",
        ink: "#0e1b18",
        accent: "#d68c45",
        pine: "#255448",
        berry: "#8b3d3d"
      },
      fontFamily: {
        sans: ["'Space Grotesk'", "sans-serif"],
        mono: ["'IBM Plex Mono'", "monospace"]
      },
      boxShadow: {
        panel: "0 20px 60px rgba(14, 27, 24, 0.12)"
      }
    }
  },
  plugins: []
} satisfies Config;
