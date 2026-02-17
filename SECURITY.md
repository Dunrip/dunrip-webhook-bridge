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

## Remediation SLA (Severity-Based Targets)

Target response windows after a validated report:

- **Critical** (RCE, auth bypass, secret exposure with active risk)
  - Acknowledge: **within 24 hours**
  - Mitigation/fix plan: **within 72 hours**
  - Patch release target: **within 7 days**
- **High** (major privilege escalation, data exposure without active exploitation)
  - Acknowledge: **within 2 business days**
  - Fix plan: **within 5 business days**
  - Patch release target: **within 14 days**
- **Medium**
  - Acknowledge: **within 5 business days**
  - Fix target: **within 30 days**
- **Low**
  - Acknowledge: **within 10 business days**
  - Fix target: **next planned maintenance release**

If timelines cannot be met, maintainers will publish a status update (risk, workaround, revised ETA).

## Existing Security Controls

This project includes several built-in protections, including:

- HMAC signature verification for webhook authenticity
- API key authentication for protected endpoints
- Input validation using FastAPI/Pydantic models
- Structured logging for security auditing
- Secret/config management through environment variables

These controls reduce risk but do not replace secure deployment and operational practices.
