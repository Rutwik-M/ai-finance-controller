/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
      },
      colors: {
        rzp: {
          blue: '#2b84ea',
          dark: '#0d2366',
          bg: '#f6f8fb',
          surface: '#ffffff',
          text: '#2d3748',
          textmuted: '#718096',
          border: '#e2e8f0'
        }
      }
    },
  },
  plugins: [],
}
