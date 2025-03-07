# Contributing to LiveChain

Thank you for your interest in contributing to LiveChain! Here are some guidelines to help you get started.

## Development Setup

1. Fork the repository
2. Clone your fork to your local machine
3. Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Development Workflow

1. Create a new branch for your changes:

```bash
git checkout -b feature/your-feature-name
```

2. Make your changes
3. Run tests to ensure everything is working:

```bash
pytest
```

4. Format your code:

```bash
black livechain tests
isort livechain tests
```

5. Run linting:

```bash
ruff livechain tests
mypy livechain
```

6. Commit your changes with a descriptive message
7. Push your branch to your fork
8. Create a pull request to the main repository

## Pull Request Guidelines

- Include a clear description of the changes and their purpose
- Include tests for new functionality
- Make sure all tests pass and linting checks pass
- Keep pull requests focused on a single topic
- Reference any related issues in your PR description

## Code Style

We follow PEP 8 with some modifications:

- Line length: 88 characters
- Use Black for formatting
- Use isort for import sorting
- Use type hints when practical

Thank you for contributing to LiveChain!
