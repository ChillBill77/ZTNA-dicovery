import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Okabe-Ito palette (colour-blind safe)
        okabe: {
          black: "#000000",
          orange: "#E69F00",
          sky: "#56B4E9",
          green: "#009E73",
          yellow: "#F0E442",
          blue: "#0072B2",
          vermillion: "#D55E00",
          purple: "#CC79A7",
        },
      },
    },
  },
  plugins: [],
};

export default config;
