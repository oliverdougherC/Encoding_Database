# Contributing to Encoding_Database

Thanks for your interest in contributing! This guide will help you get started.

## Development Setup

1. **Fork the repository** via GitHub and clone your fork:
   ```bash
   gh repo clone oliverdougherC/Encoding_Database
   cd Encoding_Database
   git remote add upstream https://github.com/oliverdougherC/Encoding_Database.git
   ```

2. **Create a feature branch** from main:
   ```bash
   git checkout -b feature/amazing-feature main
   ```

3. **Install dependencies**:
   ```bash
   # Server
   cd server
   npm ci
   npm run build

   # Frontend
   cd ../frontend
   npm ci
   npm run build

   # Client (optional)
   cd ../client
   python -m venv ../.myenv
   ../.myenv/Scripts/pip install -r requirements.txt
   ```

4. **Make your changes** and test locally:
   ```bash
   # Run server dev server
   cd server
   npm run dev

   # Run frontend dev server (separate terminal)
   cd frontend
   npm run dev
   ```

## Code Quality Checks

Before submitting a PR, ensure all CI checks pass:

- `build-frontend` — Frontend build must succeed
- `build-server` — Server build must succeed
- `audit-node` — No critical npm vulnerabilities
- `audit-python` — No critical Python vulnerabilities

## Pull Request Process

1. **Commit your changes** with clear, descriptive commit messages following conventional commit format:
   ```bash
   feat(client): add support for new encoder
   fix(server): correct endpoint typo
   docs(readme): update installation instructions
   ```

2. **Push your branch**:
   ```bash
   git push origin feature/amazing-feature
   ```

3. **Open a Pull Request** via GitHub and fill in the PR template.

4. **Request reviews** from Oliver or other maintainers.

## Coding Standards

- **TypeScript/JavaScript**: Use strict TypeScript and functional programming patterns
- **Python**: Follow PEP 8 style guide
- **Testing**: Add tests when adding new functionality
- **Documentation**: Keep README and code comments updated

## Getting Help

- Open an issue if you encounter bugs or have questions
- Check existing discussions for similar topics
- Reach out to Oliver directly if you need help

Thanks again for contributing! 🎉