# Security Testing for Brain Researcher

This directory contains comprehensive security testing infrastructure for the Brain Researcher neuroimaging platform.

## Overview

The security testing suite covers:

- **Static Application Security Testing (SAST)**: Code analysis for security vulnerabilities
- **Dynamic Application Security Testing (DAST)**: Runtime security testing
- **Authentication & Authorization Testing**: User access control validation
- **API Security Testing**: REST API vulnerability scanning
- **JWT Security Testing**: JSON Web Token implementation validation
- **Dependency Vulnerability Scanning**: Third-party package security analysis

## Quick Start

### Run All Security Tests

```bash
# Run comprehensive security scan
python tests/security/scripts/run_security_scan.py

# Run specific test types
python tests/security/scripts/run_security_scan.py --scan-type sast
python tests/security/scripts/run_security_scan.py --scan-type dast
python tests/security/scripts/run_security_scan.py --scan-type deps
```

### Run Individual Test Suites

```bash
# Authentication tests
pytest tests/security/auth/ -v

# API security tests
pytest tests/security/api/ -v

# JWT security tests
pytest tests/security/jwt/ -v
```

## Directory Structure

```
tests/security/
├── auth/                    # Authentication & authorization tests
│   └── test_authentication.py
├── api/                     # API security tests
│   └── test_api_security.py
├── jwt/                     # JWT security tests
│   └── test_jwt_security.py
├── sast/                    # Static analysis configurations
│   ├── bandit.yaml         # Bandit SAST configuration
│   ├── safety_policy.json  # Safety dependency scanning
│   └── semgrep.yml         # Semgrep security rules
├── owasp_zap/              # OWASP ZAP configurations
│   ├── zap_baseline.conf   # ZAP baseline scanning
│   ├── zap_automation.yaml # ZAP automation framework
│   └── scripts/
│       └── neuroimaging_data_check.py
├── scripts/                # Security testing automation
│   ├── run_security_scan.py        # Main security scanner
│   ├── check_secrets.py            # Hardcoded secrets detection
│   ├── check_participant_data.py   # Participant data exposure check
│   └── check_jwt_security.py       # JWT implementation validation
└── configs/                # Configuration files
    ├── pytest.ini             # Pytest security test config
    └── pre-commit-security.yaml # Pre-commit security hooks
```

## Security Test Categories

### 1. Static Application Security Testing (SAST)

**Tools Used:**
- Bandit: Python security linter
- Semgrep: Multi-language security rules
- Safety: Dependency vulnerability scanning
- Custom neuroimaging-specific checks

**What's Tested:**
- SQL injection vulnerabilities
- Cross-site scripting (XSS) prevention
- Hardcoded secrets and credentials
- Participant data exposure patterns
- Insecure cryptographic practices

```bash
# Run SAST scan
bandit -r src/brain_researcher/ -f json -o bandit-report.json
safety check --json --output safety-report.json
semgrep --config=tests/security/sast/semgrep.yml src/brain_researcher/
```

### 2. Dynamic Application Security Testing (DAST)

**Tools Used:**
- OWASP ZAP: Web application security scanner
- Custom API security tests
- Penetration testing automation

**What's Tested:**
- Authentication bypass attempts
- Session management vulnerabilities
- Input validation and sanitization
- Rate limiting effectiveness
- CORS configuration security

```bash
# Run OWASP ZAP scan
zap.sh -cmd -autorun tests/security/owasp_zap/zap_automation.yaml
```

### 3. Authentication & Authorization Testing

**Components Tested:**
- User login/logout mechanisms
- Session management
- Password complexity requirements
- Account lockout policies
- Role-based access control (RBAC)
- Multi-factor authentication (if implemented)

### 4. API Security Testing

**Security Checks:**
- Input validation and sanitization
- SQL injection prevention
- XSS prevention
- Command injection prevention
- Path traversal prevention
- CORS configuration validation
- Rate limiting implementation
- Parameter tampering protection

### 5. JWT Security Testing

**JWT Validation:**
- Token expiration handling
- Secret key strength verification
- Algorithm confusion attack prevention
- Token tampering detection
- Claim validation
- Secure token transmission

### 6. Neuroimaging-Specific Security

**Medical Data Protection:**
- Participant/subject ID exposure detection
- Medical data in error messages
- Unencrypted sensitive data storage
- Proper anonymization verification
- HIPAA compliance checks

## Configuration Files

### Bandit Configuration (`sast/bandit.yaml`)

Configures Python security scanning with neuroimaging-specific rules:
- Allows subprocess usage for neuroimaging tools (FSL, AFNI)
- Excludes test files from certain security checks
- Custom rules for participant data exposure

### Semgrep Rules (`sast/semgrep.yml`)

Custom security rules including:
- Neuroimaging data exposure patterns
- API endpoint authentication checks
- JWT security validation
- File system security checks

### OWASP ZAP Configuration (`owasp_zap/`)

Web application security scanning configuration:
- Baseline scan settings
- API-specific scan configurations
- Custom neuroimaging data exposure checks
- Authentication handling

## GitHub Actions Integration

Security testing is integrated into CI/CD pipeline:

```yaml
# .github/workflows/security.yml
- Security scanning on every PR
- Scheduled daily security scans
- Container vulnerability scanning
- Dependency vulnerability monitoring
- Security report aggregation
```

## Pre-commit Hooks

Install pre-commit security hooks:

```bash
# Copy pre-commit configuration
cp tests/security/configs/pre-commit-security.yaml .pre-commit-config.yaml

# Install pre-commit
pip install pre-commit
pre-commit install

# Run pre-commit checks
pre-commit run --all-files
```

## Security Test Reports

Security scan reports are generated in multiple formats:

- **JSON**: Machine-readable results for CI/CD integration
- **HTML**: Human-readable reports with detailed findings
- **SARIF**: GitHub Security tab compatible format

Reports are saved to:
- `security_reports/` (local runs)
- GitHub Actions artifacts (CI runs)
- GitHub Security tab (SARIF uploads)

## Customizing Security Tests

### Adding New Security Rules

1. **Bandit Rules**: Edit `sast/bandit.yaml`
2. **Semgrep Rules**: Add to `sast/semgrep.yml`
3. **API Tests**: Extend `api/test_api_security.py`
4. **Custom Checks**: Add to `scripts/` directory

### Neuroimaging-Specific Customization

The security suite includes specialized checks for neuroimaging data:

```python
# Example: Custom participant data check
def check_participant_exposure(self, code_content):
    patterns = [
        r'participant[_-]?id',
        r'subject[_-]?id',
        r'medical[_-]?record'
    ]
    # Check for exposure patterns...
```

## Security Best Practices

### For Developers

1. **Run security checks before commits**:
   ```bash
   pre-commit run --all-files
   ```

2. **Use environment variables for secrets**:
   ```python
   # Good
   api_key = os.getenv('OPENAI_API_KEY')

   # Bad
   api_key = 'sk-1234567890abcdef'
   ```

3. **Implement proper error handling**:
   ```python
   # Good
   try:
       process_participant_data(participant_hash)
   except Exception:
       logger.error("Data processing failed", exc_info=False)

   # Bad
   try:
       process_participant_data(participant_id)
   except Exception as e:
       print(f"Failed for participant {participant_id}: {e}")
   ```

### For Medical Data

1. **Always anonymize participant identifiers**
2. **Encrypt sensitive data at rest**
3. **Use secure communication channels (HTTPS)**
4. **Implement proper access controls**
5. **Audit access to sensitive data**

## Troubleshooting

### Common Issues

1. **Service Not Running**: Ensure required services are started before DAST tests
2. **Permission Errors**: Check file permissions for security scripts
3. **Missing Dependencies**: Install security tools with `pip install bandit safety semgrep`

### Debug Mode

Run security tests with verbose output:

```bash
python tests/security/scripts/run_security_scan.py --verbose
pytest tests/security/ -v -s --tb=long
```

## Contributing

When adding new security tests:

1. Follow the existing pattern for test organization
2. Add appropriate security markers (`@pytest.mark.security`)
3. Include both positive and negative test cases
4. Document neuroimaging-specific security considerations
5. Update this README with new test categories

## Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [HIPAA Security Rule](https://www.hhs.gov/hipaa/for-professionals/security/index.html)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)
- [Neuroimaging Data Sharing Best Practices](https://www.nature.com/articles/sdata201644)
