/** Tailwind config for the precompiled CSS build (standalone CLI, no Node).
 *  Mirrors the former inline Play-runtime config from layouts/base.html.
 *  Rebuild with: ./scripts/build_css.sh
 */
module.exports = {
  darkMode: 'class',
  content: [
    './templates/**/*.html',
    './app/api/pages.py', // processing page HTML is embedded in Python
    './static/js/**/*.js',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      colors: {
        bgMain:         'var(--bg-main)',
        bgCard:         'var(--bg-card)',
        bgHover:        'var(--bg-hover)',
        bgInput:        'var(--bg-input)',
        bgSkeleton:     'var(--bg-skeleton)',
        bgOverlay:      'var(--bg-overlay)',
        textBase:       'var(--text-base)',
        textMuted:      'var(--text-muted)',
        textSubtle:     'var(--text-subtle)',
        borderDefault:  'var(--border-default)',
        borderLight:    'var(--border-light)',
        borderInput:    'var(--border-input)',
      },
    },
  },
};
