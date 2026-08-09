/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        void: "#0B0F14",
        panel: "#121821",
        "panel-raised": "#1A2230",
        hairline: "#253040",
        primary: "#E6EDF5",
        muted: "#8A97A8",
        critical: "#FF6B4A",
        caution: "#F0B429",
        resolved: "#4FD1C5",
        ai: "#7C9CFF",
      },
      fontFamily: {
        display: ["var(--font-display)", "system-ui", "sans-serif"],
        body: ["var(--font-body)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        none: "0px",
        sm: "2px",
        DEFAULT: "2px",
      },
    },
  },
  plugins: [],
};
