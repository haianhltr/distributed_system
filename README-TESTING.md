# Testing Guide

This document describes how to run the comprehensive test suite for the distributed system.

## Prerequisites

1. **Docker and Docker Compose** - for running PostgreSQL test containers
2. **Python 3.9+** - for running tests
3. **Test dependencies** - install via pip

## Setup

### 1. Install Test Dependencies

```bash
# Install main server test dependencies
pip install -r main_server/test_requirements.txt

# Install main requirements if not already installed
pip install -r main_server/requirements.txt
```

### 2. Environment Setup

Tests use testcontainers to spin up a PostgreSQL instance automatically. No manual database setup required.

## Running Tests

### Run All Tests

```bash
# From project root
pytest tests/ -v
```

### Run Specific Test Suites

```bash
# Main server tests only
pytest tests/main_server/ -v

# Bot tests only  
pytest tests/bots/ -v

# Dashboard tests only
pytest tests/dashboard/ -v
```

### Run Specific Test Files

```bash
# Database tests
pytest tests/main_server/test_database.py -v

# API tests
pytest tests/main_server/test_api.py -v

# Bot functionality tests
pytest tests/bots/test_bot.py -v
```

### Run with Coverage

```bash
# Install coverage
pip install pytest-cov

# Run tests with coverage report
pytest tests/ --cov=main_server --cov=bots --cov=dashboard --cov-report=html --cov-report=term
```

## Test Categories

### Unit Tests
- **Database layer**: Connection pooling, schema validation, constraints
- **Bot logic**: Job processing, heartbeats, error handling
- **API endpoints**: Request/response validation, authentication

### Integration Tests
- **Complete job workflow**: Claim → Process → Complete
- **Bot lifecycle**: Registration → Work → Shutdown
- **Cross-service communication**: Dashboard ↔ Main Server

### Error Handling Tests
- **Network failures**: Connection timeouts, service unavailable
- **Invalid data**: Malformed requests, constraint violations
- **Resource exhaustion**: Database connection limits, memory constraints

## Test Environment

### Test Database
- Uses PostgreSQL 16 in Docker container
- Automatically created and destroyed per test session
- Clean state for each test method
- Migrations run automatically

### Mock Services
- HTTP clients mocked for external API calls
- Async operations properly handled
- Realistic error scenarios simulated

### Test Data
- Sample jobs, bots, and results created via fixtures
- Deterministic test data for reliable assertions
- Cleanup handled automatically

## Continuous Integration

### GitHub Actions (Recommended)

```yaml
name: Test Suite

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
    - uses: actions/checkout@v3
    - name: Set up Python
      uses: actions/setup-python@v3
      with:
        python-version: '3.9'
    
    - name: Install dependencies
      run: |
        pip install -r main_server/requirements.txt
        pip install -r main_server/test_requirements.txt
    
    - name: Run tests
      run: pytest tests/ -v --cov=main_server --cov=bots --cov=dashboard
```

## Test Configuration

### pytest.ini
- Async test mode enabled
- Test discovery patterns configured
- Markers for test categories (unit, integration, slow)

### conftest.py
- Database fixtures for PostgreSQL testcontainers
- HTTP client fixtures for API testing
- Sample data fixtures for consistent test data

## Performance Tests

For load testing and performance validation:

```bash
# Install additional dependencies
pip install locust

# Run performance tests (if implemented)
pytest tests/performance/ -v --timeout=300
```

## Troubleshooting

### Common Issues

1. **Docker not available**: Testcontainers requires Docker daemon
2. **Port conflicts**: Ensure ports 5432, 3001, 3002 are available
3. **Slow tests**: Database container startup can take 10-30 seconds

### Debug Mode

```bash
# Run with verbose output and don't capture stdout
pytest tests/ -v -s --tb=long

# Run single test for debugging
pytest tests/main_server/test_api.py::TestJobEndpoints::test_populate_jobs_with_auth -v -s
```

### Environment Variables

```bash
# Override test database URL
export DATABASE_URL="postgresql://test:test@localhost:5433/testdb"

# Set test admin token
export ADMIN_TOKEN="test-admin-token"

# Enable debug logging
export LOG_LEVEL="DEBUG"
```

## Test Metrics

Target test coverage: **80%+**

Current test statistics:
- **Unit tests**: ~40 test cases
- **Integration tests**: ~15 test cases  
- **Error handling**: ~20 test cases
- **Total runtime**: ~60 seconds (including container startup)

## Future Improvements

1. **Load testing** with realistic traffic patterns
2. **Chaos engineering** tests for resilience validation
3. **Security testing** for authentication and authorization
4. **Performance benchmarks** with SLA validation
5. **Contract testing** between services