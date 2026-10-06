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
          bg:      '#faf8f5',
          sidebar: '#eee8e0',
          chat:    '#e0d7cc',
          input:   '#faf8f5',
          hover:   '#b45309',
          text:    '#1c1917',
          muted:   '#78716c',
        },
      },
      boxShadow: {
        'glow': '0 0 20px -4px rgba(180, 83, 9, 0.2)',
        'glow-sm': '0 0 12px -3px rgba(180, 83, 9, 0.12)',
      },
    },
  },
  plugins: [],
}
