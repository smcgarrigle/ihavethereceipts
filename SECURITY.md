# Security PracticesFor AI agent behavior and coding style, see GEMINI.md

1. Never store sensitive data in localStorage. Use httpOnly cookies
2. Disable directory listing on your server. Never expose file structure
3. Always regenerate session IDs after login
4. Use Content Security Policy headers on every page
5. Never trust client-side validation alone. Always re-validate server-side
6. Set X-Frame-Options to DENY. Prevents clickjacking attacks
7. Strip metadata from every user-uploaded file before storing
8. Never expose stack traces or error details in production responses
9. Use short-lived presigned URLs for private file access. Never public bucket URLs
10. Implement CSRF tokens on every state-changing form or request
11. Disable autocomplete on sensitive form fields (passwords, card numbers)
12. Always hash passwords with bcrypt minimum cost factor of 12
13. Keep dependency list minimal. Every extra package is an attack surface
14. Use subresource integrity (SRI) for every external script you load
15. Never log user passwords, tokens, or PII, even by accident
16. Enforce HTTPS everywhere. Redirect all HTTP to HTTPS at server level
17. Use separate DB credentials per environment. Never share prod creds
18. Implement account lockout after 5 failed login attempts
19. Validate content-type headers on every API request
20. Never use MD5 or SHA1 for anything security-related
21. Scope OAuth tokens to minimum required permissions only
22. Use nonces for every inline script in your CSP policy
23. Monitor for dependency vulnerabilities with Snyk or similar weekly
24. Disable HTTP methods you dont use (PUT, DELETE, TRACE, OPTIONS)
25. Implement proper logout: invalidate server-side sessions, not just clear cookies
26. Use constant-time string comparison for token validation. Prevents timing attacks
27. Never cache sensitive API responses. Set Cache-Control: no-store
28. Set Referrer-Policy to strict-origin. Stop leaking URLs to third parties
29. Enforce password complexity server-side. Not just a regex on the frontend
30. Scan your docker images for vulnerabilities before every deployment
