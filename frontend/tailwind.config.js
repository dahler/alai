/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        mono: ['Fira Code', 'Cascadia Code', 'Monaco', 'Consolas', 'monospace'],
      },
      colors: {
        dark: {
          bg:      '#111118',
          sidebar: '#0a0b10',
          chat:    '#1c1d28',
          input:   '#111118',
          hover:   '#7c6ef8',
          text:    '#e8eaf2',
          muted:   '#8082a0',
        },
      },
      boxShadow: {
        'glow': '0 0 20px -4px rgba(124, 110, 248, 0.3)',
        'glow-sm': '0 0 12px -3px rgba(124, 110, 248, 0.2)',
      },
    },
  },
  plugins: [],
}
