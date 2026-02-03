terraform {
  required_providers {
    coder = {
      source = "coder/coder"
    }
    docker = {
      source = "kreuzwerker/docker"
    }
  }
}

provider "coder" {}

provider "docker" {}

data "coder_provisioner" "me" {}

data "coder_workspace" "me" {}

data "coder_workspace_owner" "me" {}

# Parameters
data "coder_parameter" "git_repo_url" {
  name         = "git_repo_url"
  display_name = "Git Repository URL"
  description  = "The HTTPS URL of the Git repository to clone"
  type         = "string"
  mutable      = false
  default      = ""
}

data "coder_parameter" "git_branch" {
  name         = "git_branch"
  display_name = "Git Branch"
  description  = "The branch to checkout"
  type         = "string"
  mutable      = true
  default      = "main"
}

data "coder_parameter" "python_version" {
  name         = "python_version"
  display_name = "Python Version"
  description  = "Python interpreter version"
  type         = "string"
  mutable      = false
  default      = "3.11"
  option {
    name  = "Python 3.11"
    value = "3.11"
  }
  option {
    name  = "Python 3.12"
    value = "3.12"
  }
  option {
    name  = "Python 3.10"
    value = "3.10"
  }
}

# Agent
resource "coder_agent" "main" {
  arch           = data.coder_provisioner.me.arch
  os             = "linux"
  startup_script = <<-EOT
    set -e

    # Install Python and common tools
    sudo apt-get update
    sudo apt-get install -y python${data.coder_parameter.python_version.value} python${data.coder_parameter.python_version.value}-venv python3-pip

    # Install uv for fast package management
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"

    # Clone repository if specified
    if [ -n "${data.coder_parameter.git_repo_url.value}" ]; then
      git clone --branch ${data.coder_parameter.git_branch.value} ${data.coder_parameter.git_repo_url.value} ~/project
      cd ~/project

      # Create virtual environment and install dependencies
      python${data.coder_parameter.python_version.value} -m venv .venv
      source .venv/bin/activate

      # Auto-detect and install dependencies
      if [ -f "pyproject.toml" ]; then
        uv pip install -e ".[dev]" 2>/dev/null || uv pip install -e .
      elif [ -f "requirements.txt" ]; then
        uv pip install -r requirements.txt
      elif [ -f "setup.py" ]; then
        uv pip install -e .
      fi
    fi

    # Start code-server
    code-server --auth none --port 13337 &
  EOT

  metadata {
    display_name = "CPU Usage"
    key          = "cpu"
    script       = "coder stat cpu"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "Memory Usage"
    key          = "mem"
    script       = "coder stat mem"
    interval     = 10
    timeout      = 1
  }
}

# Code Server App
resource "coder_app" "code-server" {
  agent_id     = coder_agent.main.id
  slug         = "code-server"
  display_name = "VS Code"
  url          = "http://localhost:13337/?folder=/home/coder/project"
  icon         = "/icon/code.svg"
  subdomain    = true
  share        = "owner"

  healthcheck {
    url       = "http://localhost:13337/healthz"
    interval  = 5
    threshold = 6
  }
}

# Docker container
resource "docker_image" "main" {
  name = "codercom/enterprise-base:ubuntu"
}

resource "docker_container" "workspace" {
  count = data.coder_workspace.me.start_count
  image = docker_image.main.image_id
  name  = "coder-${data.coder_workspace_owner.me.name}-${lower(data.coder_workspace.me.name)}"

  hostname = data.coder_workspace.me.name

  entrypoint = ["sh", "-c", coder_agent.main.init_script]

  env = [
    "CODER_AGENT_TOKEN=${coder_agent.main.token}",
    "PYTHONDONTWRITEBYTECODE=1",
    "PYTHONUNBUFFERED=1",
  ]

  host {
    host = "host.docker.internal"
    ip   = "host-gateway"
  }

  volumes {
    container_path = "/home/coder"
    volume_name    = docker_volume.home.name
    read_only      = false
  }
}

resource "docker_volume" "home" {
  name = "coder-${data.coder_workspace.me.id}-home"

  lifecycle {
    ignore_changes = all
  }
}
