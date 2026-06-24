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
          bg: '#27272a',
          sidebar: '#18181b',
          chat: '#3f3f46',
          input: '#27272a',
          hover: '#6366f1',
          text: '#f4f4f5',
          muted: '#a1a1aa',
        },
      },
    },
  },
  plugins: [],
}
