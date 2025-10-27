# Testing and Deployment Workflow Procedure

## ENTSO-E Day Ahead Prices Project - CI/CD Guide

This document provides a comprehensive workflow for testing, quality assurance, and automated deployment of the ENTSO-E Day Ahead Prices project.

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Local Development Workflow](#local-development-workflow)
4. [Testing Procedures](#testing-procedures)
5. [Git Workflow](#git-workflow)
6. [Automated CI/CD Pipeline](#automated-cicd-pipeline)
7. [Deployment Procedures](#deployment-procedures)
8. [Quality Gates](#quality-gates)
9. [Troubleshooting](#troubleshooting)
10. [Checklists](#checklists)

## Overview

The project uses a comprehensive CI/CD pipeline with GitHub Actions that includes:

- Multi-version Python testing (3.9, 3.10, 3.11, 3.12)
- Code quality checks (linting, type checking, security scanning)
- Automated testing with coverage reporting
- Docker image building and testing
- Performance testing
- Automated deployment to staging and production
- Security vulnerability scanning

## Prerequisites

### Required Tools

- Python 3.9+ (preferably 3.11)
- Git
- Docker and Docker Compose
- GitHub account with repository access
- ENTSO-E API key

### Environment Setup

```bash
# Clone the repository
git clone <repository-url>
cd "day ahead prijzen"

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env  # Create from template
# Edit .env with your ENTSO-E API key
```

### Required Environment Variables

```bash
ENTSOE_API_KEY=your_actual_api_key_here
ZONE_EIC=10YNL----------L
CACHE_DIR=./cache
DATA_ROOT=./data
```

## Local Development Workflow

### 1. Pre-Development Setup

```bash
# Ensure you're on the latest main branch
git checkout main
git pull origin main

# Create feature branch
git checkout -b feature/your-feature-name

# Ensure environment is clean
rm -rf cache/* data/*
mkdir -p cache data
```

### 2. Development Cycle

```bash
# Make your changes
# ...

# Run local tests frequently
python -m pytest tests/ -v

# Check code quality
flake8 . --max-line-length=127
mypy ha_entsoe.py api_server.py --ignore-missing-imports

# Run security check
bandit -r . --severity-level medium
```

### 3. Pre-Commit Validation

Before committing any changes, run the complete local test suite:

```bash
# Full test suite with coverage
python -m pytest tests/ --cov=. --cov-report=html --cov-report=term-missing -v

# Verify API functionality
python -c "
import api_server
from fastapi.testclient import TestClient
client = TestClient(api_server.app)
response = client.get('/system/health')
assert response.status_code == 200
print('✅ API health check passed')
"

# Test Docker build
docker build -t entsoe-api-test .
docker run --rm -e ENTSOE_API_KEY=test-key entsoe-api-test python -c "import ha_entsoe; print('✅ Docker build successful')"
```

## Testing Procedures

### 1. Unit Tests

```bash
# Run all unit tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_ha_entsoe.py -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=html

# Run tests for specific functionality
python -m pytest tests/ -k "test_price" -v
```

### 2. Integration Tests

```bash
# Run integration tests (marked with @pytest.mark.integration)
python -m pytest tests/ -m integration -v

# Run slow tests (marked with @pytest.mark.slow)
python -m pytest tests/ -m slow -v
```

### 3. API Testing

```bash
# Start the API server
uvicorn api_server:app --reload --port 8000 &

# Test endpoints manually
curl http://localhost:8000/system/health
curl http://localhost:8000/energy/prices/dayahead
curl http://localhost:8000/energy/prices/cheapest

# Stop the server
pkill -f uvicorn
```

### 4. Docker Testing

```bash
# Build and test Docker image
docker build -t entsoe-api-local .

# Test with docker-compose
docker-compose up --build -d
docker-compose logs
docker-compose down

# Test scheduled version
docker-compose -f docker-compose_scheduled.yml up --build -d
docker-compose -f docker-compose_scheduled.yml logs
docker-compose -f docker-compose_scheduled.yml down
```

## Git Workflow

### Branch Strategy

- `main`: Production-ready code
- `develop`: Integration branch for features
- `feature/*`: Feature development branches
- `hotfix/*`: Critical production fixes
- `release/*`: Release preparation branches

### Commit Guidelines

```bash
# Use conventional commit format
git commit -m "feat: add new price analysis endpoint"
git commit -m "fix: resolve timezone handling in price calculation"
git commit -m "docs: update API documentation"
git commit -m "test: add integration tests for cheapest hours"
git commit -m "refactor: improve error handling structure"
```

### Pull Request Process

1. Create feature branch from `develop`
2. Make changes and commit
3. Push branch and create Pull Request
4. Ensure all CI checks pass
5. Request code review
6. Merge after approval

## Automated CI/CD Pipeline

### Pipeline Triggers

- **Push to main/develop**: Full pipeline including deployment
- **Pull Requests**: Testing and validation only
- **Manual trigger**: Available for emergency deployments

### Pipeline Stages

#### 1. Testing Stage

- **Multi-version testing**: Python 3.9, 3.10, 3.11, 3.12
- **Code quality**: Flake8 linting, MyPy type checking
- **Security scanning**: Bandit security analysis
- **Unit tests**: Full pytest suite with coverage
- **Coverage reporting**: Codecov integration

#### 2. Docker Build Stage

- **Multi-platform builds**: linux/amd64, linux/arm64
- **Image testing**: Verify imports and basic functionality
- **Registry push**: Push to Docker Hub (main branch only)
- **Vulnerability scanning**: Trivy security scan

#### 3. Performance Testing Stage (main branch only)

- **Load testing**: Locust-based performance tests
- **API benchmarking**: Response time and throughput metrics
- **Resource monitoring**: Memory and CPU usage analysis

#### 4. Security Scanning Stage

- **Dependency scanning**: Check for vulnerable packages
- **Container scanning**: Trivy vulnerability assessment
- **SARIF reporting**: Upload results to GitHub Security tab

#### 5. Deployment Stages

- **Staging deployment**: Automatic deployment to staging (develop branch)
- **Production deployment**: Automatic deployment to production (main branch)
- **Smoke tests**: Post-deployment verification

### Monitoring CI/CD Status

```bash
# Check latest workflow runs
gh run list

# View specific run details
gh run view <run-id>

# Download artifacts
gh run download <run-id>
```

## Deployment Procedures

### Staging Deployment (develop branch)

```bash
# Automatic deployment triggered by push to develop
git checkout develop
git merge feature/your-feature
git push origin develop

# Monitor deployment
gh run watch
```

### Production Deployment (main branch)

```bash
# Create release branch
git checkout develop
git checkout -b release/v1.2.0

# Update version numbers and changelog
# ... make necessary changes ...

# Merge to main
git checkout main
git merge release/v1.2.0
git tag v1.2.0
git push origin main --tags

# Monitor production deployment
gh run watch
```

### Manual Deployment

```bash
# Emergency deployment (use with caution)
gh workflow run "CI/CD Pipeline" --ref main

# Deploy specific version
docker pull your-username/entsoe-api:v1.2.0
docker-compose up -d
```

### Rollback Procedures

```bash
# Quick rollback using Docker
docker pull your-username/entsoe-api:v1.1.0
docker-compose down
docker-compose up -d

# Git-based rollback
git checkout main
git revert <commit-hash>
git push origin main
```

## Quality Gates

### Automated Quality Checks

1. **Code Coverage**: Minimum 80% coverage required
2. **Linting**: Zero critical flake8 violations
3. **Security**: No high-severity security issues
4. **Type Checking**: MyPy validation (warnings allowed initially)
5. **Tests**: All tests must pass across Python versions

### Manual Quality Checks

1. **Code Review**: Required for all Pull Requests
2. **Documentation**: Update relevant documentation
3. **Breaking Changes**: Document in CHANGELOG.md
4. **Performance**: Verify no significant performance regression

### Release Criteria

- [ ] All automated tests pass
- [ ] Code coverage ≥ 80%
- [ ] No critical security vulnerabilities
- [ ] Documentation updated
- [ ] CHANGELOG.md updated
- [ ] Version number incremented
- [ ] Staging deployment successful
- [ ] Manual testing completed

## Troubleshooting

### Common Issues

#### Test Failures

```bash
# Check test environment
python -c "import os; print('API Key:', 'ENTSOE_API_KEY' in os.environ)"

# Run tests with verbose output
python -m pytest tests/ -v -s

# Run specific failing test
python -m pytest tests/test_api_server.py::TestPriceEndpoints::test_get_dayahead_prices_success -v -s
```

#### Docker Build Issues

```bash
# Check Docker daemon
docker info

# Build with verbose output
docker build --no-cache --progress=plain -t entsoe-api-debug .

# Check container logs
docker run --rm entsoe-api-debug python -c "import sys; print(sys.path)"
```

#### CI/CD Pipeline Issues

```bash
# Check workflow syntax
gh workflow view "CI/CD Pipeline"

# View recent failures
gh run list --status failure

# Download logs for debugging
gh run download <run-id>
```

### Performance Issues

```bash
# Profile API performance
python -m cProfile -o profile.stats api_server.py

# Monitor resource usage
docker stats

# Check database connections (if applicable)
# Monitor cache hit rates
```

## Checklists

### Pre-Commit Checklist

- [ ] All tests pass locally
- [ ] Code coverage maintained
- [ ] No linting errors
- [ ] Security scan clean
- [ ] Documentation updated
- [ ] Environment variables documented
- [ ] Docker build successful

### Pre-Release Checklist

- [ ] Version number updated
- [ ] CHANGELOG.md updated
- [ ] All tests pass in CI
- [ ] Security scan clean
- [ ] Performance tests pass
- [ ] Staging deployment successful
- [ ] Manual testing completed
- [ ] Documentation reviewed
- [ ] Breaking changes documented

### Post-Deployment Checklist

- [ ] Health checks pass
- [ ] API endpoints responding
- [ ] Logs show no errors
- [ ] Performance metrics normal
- [ ] Monitoring alerts configured
- [ ] Rollback plan ready
- [ ] Team notified of deployment

### Emergency Response Checklist

- [ ] Identify issue scope
- [ ] Check recent deployments
- [ ] Review error logs
- [ ] Implement immediate fix or rollback
- [ ] Monitor system recovery
- [ ] Document incident
- [ ] Schedule post-mortem
- [ ] Update procedures if needed

## Best Practices

### Development

1. **Test-Driven Development**: Write tests before implementation
2. **Small Commits**: Make frequent, focused commits
3. **Branch Hygiene**: Keep branches short-lived and focused
4. **Code Reviews**: Always review code before merging
5. **Documentation**: Update docs with code changes

### Testing

1. **Comprehensive Coverage**: Aim for >80% test coverage
2. **Test Isolation**: Each test should be independent
3. **Mock External Dependencies**: Use mocks for API calls
4. **Performance Testing**: Include performance regression tests
5. **Security Testing**: Regular security scans

### Deployment

1. **Gradual Rollouts**: Deploy to staging first
2. **Monitoring**: Monitor deployments closely
3. **Rollback Ready**: Always have a rollback plan
4. **Documentation**: Document deployment procedures
5. **Communication**: Notify team of deployments

## Security Considerations

### API Security

- Always use HTTPS in production
- Implement rate limiting
- Validate all inputs
- Use secure headers
- Monitor for suspicious activity

### Secrets Management

- Never commit secrets to Git
- Use environment variables
- Rotate API keys regularly
- Use GitHub Secrets for CI/CD
- Audit secret access

### Container Security

- Use minimal base images
- Scan for vulnerabilities
- Run as non-root user
- Keep dependencies updated
- Monitor container activity

---

## Support and Contact

For questions about this workflow or issues with the CI/CD pipeline:

1. Check the [Troubleshooting](#troubleshooting) section
2. Review recent GitHub Actions runs
3. Check project documentation
4. Create an issue in the repository
5. Contact the development team

---

_Last updated: October 2025_
_Version: 1.0_
