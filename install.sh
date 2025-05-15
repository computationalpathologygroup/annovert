#!/bin/bash
set -e

echo "Installing annovert..."

if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS_TYPE="linux"
    if command -v apt-get &> /dev/null; then
        PACKAGE_MANAGER="apt"
    elif command -v dnf &> /dev/null; then
        PACKAGE_MANAGER="dnf"
    elif command -v yum &> /dev/null; then
        PACKAGE_MANAGER="yum"
    else
        PACKAGE_MANAGER="unknown"
    fi
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS_TYPE="macos"
    if command -v brew &> /dev/null; then
        PACKAGE_MANAGER="brew"
    else
        PACKAGE_MANAGER="unknown"
    fi
elif [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    OS_TYPE="windows"
    PACKAGE_MANAGER="unknown"
else
    OS_TYPE="unknown"
    PACKAGE_MANAGER="unknown"
fi

echo "Detected OS: $OS_TYPE with package manager: $PACKAGE_MANAGER"

if ! command -v uv &> /dev/null; then
    echo "Installing uv package manager..."
    
    if [[ "$OS_TYPE" == "linux" ]] || [[ "$OS_TYPE" == "macos" ]]; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.cargo/bin:$PATH"
    elif [[ "$OS_TYPE" == "windows" ]]; then
        echo "Please install uv manually on Windows:"
        echo "curl -LsSf https://astral.sh/uv/install.ps1 | powershell"
        exit 1
    else
        echo "Could not install uv automatically for your OS."
        echo "Please install uv manually following instructions at: https://docs.astral.sh/uv/installation/"
        exit 1
    fi
    
    echo "Installed uv version:"
    uv --version
fi

if [[ "$VIRTUAL_ENV" == "" ]]; then
    if [ -d ".venv" ]; then
        echo "Activating existing virtual environment..."
        source .venv/bin/activate
    else
        echo "Creating virtual environment with uv..."
        uv venv .venv
        source .venv/bin/activate
    fi
fi

echo "Installing package in development mode with uv..."
uv pip install -e .

echo "Installing development dependencies with uv..."
uv pip install ruff pytest

echo ""
echo "Installation complete!"
echo ""
