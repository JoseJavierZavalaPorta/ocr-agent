/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: '#0f1117',
          card: '#1a1d27',
          border: '#2a2d3e',
          hover: '#22253a',
        },
        accent: {
          DEFAULT: '#6366f1',
          hover: '#4f52d3',
          light: '#818cf8',
        },
        success: '#22c55e',
        warning: '#f59e0b',
        error: '#ef4444',
        muted: '#64748b',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
    },
  },
  plugins: [],
}
