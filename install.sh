#!/usr/bin/env bash
# pipefail: without it a pipeline's exit code is the LAST command's, so e.g.
# a failed `curl | sudo bash` would be silently swallowed under plain -e.
set -eo pipefail

# =============================================================================
# CoStaff - Installer
# Supports: macOS (12+), Ubuntu (20.04 / 22.04 / 24.04)
# Usage: curl -fsSL https://raw.githubusercontent.com/costaff-ai/costaff/main/install.sh | bash
# =============================================================================

REPO_URL="${COSTAFF_REPO_URL:-https://github.com/costaff-ai/costaff.git}"
COSTAFF_BASE="$HOME/.costaff"      # runtime parent directory
COSTAFF_DIR="$COSTAFF_BASE/costaff"  # git clone target (CLI core)
RUNTIME_DIR="$COSTAFF_DIR"
VENV_DIR="$COSTAFF_BASE/.venv"
PYTHON_VERSION="3.12"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[1;32m'
BLUE='\033[1;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

step()    { echo -e "\n${BLUE}==>${RESET} ${BOLD}$1${RESET}"; }
success() { echo -e "${GREEN}✔${RESET}  $1"; }
warn()    { echo -e "${YELLOW}⚠${RESET}  $1"; }
die()     { echo -e "${RED}✖${RESET}  $1" >&2; exit 1; }

MANUAL_STEPS=()
add_manual() { MANUAL_STEPS+=("$1"); }

# =============================================================================
# Detect OS
# =============================================================================
detect_os() {
    case "$(uname -s)" in
        Darwin) echo "mac" ;;
        Linux)
            if [ -f /etc/os-release ]; then
                . /etc/os-release
                case "$ID" in
                    ubuntu|debian) echo "ubuntu" ;;
                    *) die "Unsupported Linux distro: $ID. Only Ubuntu/Debian is supported." ;;
                esac
            else
                die "Cannot detect Linux distro."
            fi
            ;;
        *) die "Unsupported OS: $(uname -s). Only macOS and Ubuntu are supported." ;;
    esac
}

# =============================================================================
# macOS
# =============================================================================
install_mac() {
    # Xcode Command Line Tools
    step "Checking Xcode Command Line Tools..."
    if ! xcode-select -p &>/dev/null; then
        warn "Xcode Command Line Tools not found."
        warn "A dialog will appear — please click 'Install' to continue."
        xcode-select --install 2>/dev/null || true
        echo "Waiting for Xcode CLT installation to complete..."
        until xcode-select -p &>/dev/null; do sleep 5; done
        success "Xcode Command Line Tools installed."
    else
        success "Xcode Command Line Tools already installed."
    fi

    # Homebrew
    step "Checking Homebrew..."
    if ! command -v brew &>/dev/null; then
        echo "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # Add brew to PATH for Apple Silicon
        if [ -f /opt/homebrew/bin/brew ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        fi
        success "Homebrew installed."
    else
        success "Homebrew already installed."
    fi

    # Python
    step "Checking Python ${PYTHON_VERSION}..."
    if ! command -v python${PYTHON_VERSION} &>/dev/null; then
        echo "Installing Python ${PYTHON_VERSION} via Homebrew..."
        brew install python@${PYTHON_VERSION}
        success "Python ${PYTHON_VERSION} installed."
    else
        success "Python ${PYTHON_VERSION} already installed."
    fi

    # Docker Desktop
    step "Checking Docker..."
    if ! command -v docker &>/dev/null; then
        echo "Installing Docker Desktop via Homebrew..."
        brew install --cask docker
        success "Docker Desktop installed."
    else
        success "Docker already installed."
    fi
    ensure_docker_running_mac

    PYTHON_BIN="python${PYTHON_VERSION}"
    SHELL_RC="$HOME/.zshrc"
}

# Launch Docker Desktop and wait for the daemon so the user doesn't hit
# "Cannot connect to Docker daemon" on their very first `costaff start`.
ensure_docker_running_mac() {
    if docker info &>/dev/null; then
        success "Docker daemon is running."
        return
    fi
    echo "Launching Docker Desktop..."
    open -a Docker 2>/dev/null || open -a "Docker Desktop" 2>/dev/null || true
    echo -n "Waiting for the Docker daemon (up to 90s)"
    for _ in $(seq 1 45); do
        if docker info &>/dev/null; then
            echo ""
            success "Docker daemon is ready."
            return
        fi
        echo -n "."
        sleep 2
    done
    echo ""
    warn "Docker daemon did not come up automatically (first launch may need you to accept the Docker Desktop terms)."
    add_manual "Open Docker Desktop from Launchpad and wait until the whale icon appears in the menu bar, then come back here."
}

# =============================================================================
# Ubuntu / Debian
# =============================================================================
install_ubuntu() {
    step "Updating apt..."
    sudo apt-get update -q

    # Python
    step "Checking Python ${PYTHON_VERSION}..."
    if ! command -v python${PYTHON_VERSION} &>/dev/null; then
        echo "Adding deadsnakes PPA for Python ${PYTHON_VERSION}..."
        sudo apt-get install -y software-properties-common
        sudo add-apt-repository -y ppa:deadsnakes/ppa
        sudo apt-get update -q
        sudo apt-get install -y python${PYTHON_VERSION} python${PYTHON_VERSION}-venv
        # python3.x-distutils no longer exists on Ubuntu 24.04+ (Python 3.12
        # dropped distutils); installing it unconditionally aborts the whole
        # script under `set -e`. Install only where the package still exists.
        if apt-cache show python${PYTHON_VERSION}-distutils &>/dev/null; then
            sudo apt-get install -y python${PYTHON_VERSION}-distutils
        else
            warn "python${PYTHON_VERSION}-distutils not available — OK on Ubuntu 24.04+ (setuptools replaces it)."
        fi
        success "Python ${PYTHON_VERSION} installed."
    else
        success "Python ${PYTHON_VERSION} already installed."
    fi
    # Ensure venv module is present even when Python is already installed:
    # Ubuntu Minimal ships python3.x without the venv module by default.
    sudo apt-get install -y python${PYTHON_VERSION}-venv

    # Git & Curl
    step "Checking git and curl..."
    sudo apt-get install -y git curl
    success "git and curl ready."

    # Docker Engine
    step "Checking Docker..."
    if ! command -v docker &>/dev/null; then
        echo "Installing Docker Engine..."
        curl -fsSL https://get.docker.com | sudo bash
        sudo usermod -aG docker "$USER"
        success "Docker Engine installed."
        warn "You have been added to the 'docker' group."
        add_manual "Log out and log back in (or run 'newgrp docker' in a new terminal) so Docker can run without sudo."
    else
        success "Docker already installed."
    fi
    # Make sure the daemon itself is up (a reboot or fresh VM often leaves it stopped).
    if ! sudo docker info &>/dev/null; then
        echo "Starting Docker daemon..."
        sudo systemctl enable --now docker 2>/dev/null || true
        if sudo docker info &>/dev/null; then
            success "Docker daemon started."
        else
            warn "Could not start the Docker daemon automatically."
            add_manual "Start Docker with 'sudo systemctl start docker' before running 'costaff start'."
        fi
    fi

    PYTHON_BIN="python${PYTHON_VERSION}"
    SHELL_RC="$HOME/.bashrc"
}

# =============================================================================
# Common: Clone & Install CLI
# =============================================================================
install_costaff() {
    # Create runtime directory structure
    step "Creating runtime directory structure..."
    mkdir -p "$COSTAFF_BASE/costaff-agent"
    mkdir -p "$COSTAFF_BASE/costaff-channel"
    mkdir -p "$COSTAFF_BASE/workspace"
    mkdir -p "$COSTAFF_BASE/workspace/shared"
    success "Runtime directories ready at $COSTAFF_BASE"

    # Clone repo
    step "Downloading CoStaff Agent..."
    GITHUB_URL="https://github.com/costaff-ai/costaff.git"
    if [ -d "$COSTAFF_DIR/.git" ]; then
        warn "CoStaff Agent already exists at $COSTAFF_DIR — pulling latest changes..."
        # Always ensure remote points to GitHub (not a local dev path)
        git -C "$COSTAFF_DIR" remote set-url origin "$GITHUB_URL" 2>/dev/null || true
        git -C "$COSTAFF_DIR" pull --ff-only
    else
        git clone "$REPO_URL" "$COSTAFF_DIR"
        # If cloned from a local path, add GitHub as the canonical remote
        current_remote=$(git -C "$COSTAFF_DIR" remote get-url origin 2>/dev/null || true)
        if [[ "$current_remote" != http* && "$current_remote" != git@* ]]; then
            git -C "$COSTAFF_DIR" remote set-url origin "$GITHUB_URL"
            success "Remote set to GitHub."
        fi
    fi
    success "CoStaff Agent at $COSTAFF_DIR"

    # Write COSTAFF_WORKSPACE_DIR to .env so docker-compose bind mount resolves correctly
    ENV_FILE="$COSTAFF_DIR/.env"
    if [ ! -f "$ENV_FILE" ] && [ -f "$COSTAFF_DIR/.env.template" ]; then
        cp "$COSTAFF_DIR/.env.template" "$ENV_FILE"
    fi
    touch "$ENV_FILE"
    if ! grep -q "^COSTAFF_WORKSPACE_DIR=" "$ENV_FILE" 2>/dev/null; then
        echo "COSTAFF_WORKSPACE_DIR=$COSTAFF_BASE/workspace" >> "$ENV_FILE"
        success "COSTAFF_WORKSPACE_DIR written to .env"
    fi

    # Create venv & install CLI
    step "Installing CoStaff CLI..."
    $PYTHON_BIN -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip -q
    "$VENV_DIR/bin/pip" install -e "$COSTAFF_DIR" -q
    success "CoStaff CLI installed."

    # Add to PATH
    step "Configuring PATH..."
    EXPORT_PATH="export PATH=\"$VENV_DIR/bin:\$PATH\""
    if ! grep -qF "$VENV_DIR/bin" "$SHELL_RC" 2>/dev/null; then
        echo "" >> "$SHELL_RC"
        echo "# CoStaff Agent CLI" >> "$SHELL_RC"
        echo "$EXPORT_PATH" >> "$SHELL_RC"
        success "Added costaff to PATH in $SHELL_RC"
    else
        success "PATH already configured."
    fi

    export PATH="$VENV_DIR/bin:$PATH"
}

# =============================================================================
# Print manual steps summary
# =============================================================================
print_manual_steps() {
    echo ""
    echo -e "${BOLD}============================================${RESET}"
    echo -e "${BOLD}  Installation complete!${RESET}"
    echo -e "${BOLD}============================================${RESET}"

    if [ ${#MANUAL_STEPS[@]} -gt 0 ]; then
        echo ""
        echo -e "${YELLOW}${BOLD}Before running 'costaff onboard', please complete these manual steps:${RESET}"
        echo ""
        for i in "${!MANUAL_STEPS[@]}"; do
            echo -e "  ${BOLD}$((i+1)).${RESET} ${MANUAL_STEPS[$i]}"
        done
        echo ""
        echo -e "  ${BOLD}$((${#MANUAL_STEPS[@]}+1)).${RESET} Reload your shell: ${BOLD}source $SHELL_RC${RESET}"
        echo ""
        echo -e "  Then run: ${GREEN}${BOLD}costaff onboard${RESET}"
    else
        echo ""
        echo -e "  Run the following to get started:"
        echo ""
        echo -e "    ${BOLD}source $SHELL_RC${RESET}"
        echo -e "    ${GREEN}${BOLD}costaff onboard${RESET}"
        echo ""
    fi

    echo -e "${BOLD}============================================${RESET}"
    echo ""
}

# =============================================================================
# Run onboard
# =============================================================================
run_onboard() {
    if [ ${#MANUAL_STEPS[@]} -gt 0 ]; then
        # There are manual steps — don't auto-run onboard
        return
    fi

    if [ ! -t 0 ]; then
        # stdin is a pipe (`curl … | bash`): the interactive wizard would
        # EOF on every prompt and write a half-empty .env. Hand off instead.
        warn "Skipping the setup wizard — no terminal attached (piped install)."
        echo -e "  Run it yourself next: ${GREEN}${BOLD}costaff onboard${RESET}"
        return
    fi

    # Unset legacy env var so _runtime_root defaults to ~/.costaff
    unset COSTAFF_HOME

    echo -e "${BOLD}Starting costaff onboard...${RESET}\n"
    costaff onboard
}

# =============================================================================
# Main
# =============================================================================
main() {
    echo ""
    echo -e "${BOLD}  CoStaff Agent Installer${RESET}"
    echo -e "  ─────────────────────"
    echo ""

    OS=$(detect_os)

    case "$OS" in
        mac)    install_mac ;;
        ubuntu) install_ubuntu ;;
    esac

    install_costaff
    print_manual_steps
    run_onboard

    echo ""
    echo -e "${BOLD}============================================${RESET}"
    echo -e "  Next steps:"
    echo -e "    ${BOLD}source $SHELL_RC${RESET}"
    echo -e "    ${GREEN}${BOLD}costaff start${RESET}"
    echo -e "${BOLD}============================================${RESET}"
    echo ""
}

main
