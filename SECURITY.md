# Security Policy

## Reporting a Vulnerability

If you discover a security issue, please report it privately:

- Email: **mixbeking@gmail.com**
- Or use: **GitHub Security Advisories** (preferred)

Please include:
- Description of the issue
- Steps to reproduce
- Potential impact
- Any suggested remediation

We will acknowledge reports promptly and work on a fix as quickly as possible.

## Supported Versions

Security updates are provided for:

- Latest `main` branch
- Most recent tagged release

Older versions may not receive fixes.

## Existing Security Controls

This project includes several built-in protections, including:

- HMAC signature verification for webhook authenticity
- API key authentication for protected endpoints
- Input validation using FastAPI/Pydantic models
- Structured logging for security auditing
- Secret/config management through environment variables

These controls reduce risk but do not replace secure deployment and operational practices.
