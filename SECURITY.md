# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.5.x   | :white_check_mark: |
| < 0.5   | :x:                |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please **do not open a public issue**.

Instead, report it privately through **GitHub Security Advisories**:

1. Go to the **Security** tab on this repository
2. Click **Report a vulnerability**
3. Describe the vulnerability and provide reproduction steps

You will receive a confirmation within **48 hours** and regular updates as we investigate.

## Scope

This policy covers **self-hosted deployments** of the Vozonda application, including:

- The Python API server (`apps/api`)
- The Svelte web frontend (`apps/web`)
- Configuration files and deployment scripts shipped with this repository

Third-party TTS services (Voxtral, Kokoro, Chatterbox, etc.), external LLM providers, and infrastructure not part of this repository are **out of scope**. We recommend you treat those as separate security boundaries.

## Bug Bounty

There is **no bug bounty program** for Vozonda. Responsible disclosure through GitHub Security Advisories is appreciated and handled promptly.