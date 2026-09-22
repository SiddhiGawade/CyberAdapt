/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        'cyber-bg':    '#050B14',
        'cyber-card':  '#0A1324',
        'cyber-card2': '#0E1A32',
        'cyber-cyan':  '#00E5FF',
        'cyber-red':   '#FF2E56',
        'cyber-amber': '#FF9900',
        'cyber-green': '#00FF9D',
        'cyber-dim':   '#3A4A6B',
        'cyber-text':  '#8B9DC3',
        'cyber-border': 'rgba(0, 229, 255, 0.15)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      boxShadow: {
        'glow-cyan':  '0 0 15px rgba(0, 229, 255, 0.25), 0 0 45px rgba(0, 229, 255, 0.08)',
        'glow-red':   '0 0 15px rgba(255, 46, 86, 0.25)',
        'glow-green': '0 0 15px rgba(0, 255, 157, 0.25)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow':       'glowPulse 2s ease-in-out infinite alternate',
        'slide-in':   'slideIn 0.3s ease-out',
        'fade-in':    'fadeIn 0.4s ease-out',
      },
      keyframes: {
        glowPulse: {
          '0%':   { boxShadow: '0 0 5px rgba(0,229,255,0.2)' },
          '100%': { boxShadow: '0 0 20px rgba(0,229,255,0.4), 0 0 60px rgba(0,229,255,0.1)' },
        },
        slideIn: {
          '0%':   { opacity: 0, transform: 'translateY(-10px)' },
          '100%': { opacity: 1, transform: 'translateY(0)' },
        },
        fadeIn: {
          '0%':   { opacity: 0 },
          '100%': { opacity: 1 },
        },
      },
    },
  },
  plugins: [],
};
