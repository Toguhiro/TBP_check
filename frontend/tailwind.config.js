/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // ダークテーマ用カラーパレット
        dark: {
          bg: '#0f1117',
          surface: '#1a1d27',
          card: '#22263a',
          border: '#2e3350',
          text: '#e2e8f0',
          muted: '#94a3b8',
        },
        accent: {
          blue: '#3b82f6',
          green: '#22c55e',
          yellow: '#eab308',
          red: '#ef4444',
          orange: '#f97316',
        },
      },
    },
  },
  plugins: [],
}
