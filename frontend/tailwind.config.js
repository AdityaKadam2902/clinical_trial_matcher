/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: '#FAF9F6',
        ink: {
          DEFAULT: '#1C1B18',
          muted: '#57534E',
          faint: '#8A857E',
        },
        line: '#E8E5DF',
        accent: {
          DEFAULT: '#0F766E',
          hover: '#115E59',
          soft: '#F0F7F6',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px 0 rgb(28 27 24 / 0.04)',
        'card-hover': '0 1px 2px 0 rgb(28 27 24 / 0.04), 0 10px 24px -8px rgb(28 27 24 / 0.10)',
      },
    },
  },
  plugins: [],
}
