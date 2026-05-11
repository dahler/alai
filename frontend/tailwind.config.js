/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        dark: {
          bg: '#1a1a2e',
          sidebar: '#16213e',
          chat: '#0f3460',
          input: '#1a1a2e',
          hover: '#e94560',
          text: '#eaeaea',
          muted: '#a0a0a0',
        },
      },
    },
  },
  plugins: [],
}
