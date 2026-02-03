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

data "coder_parameter" "node_version" {
  name         = "node_version"
  display_name = "Node.js Version"
  description  = "Node.js runtime version"
  type         = "string"
  mutable      = false
  default      = "20"
  option {
    name  = "Node.js 20 (LTS)"
    value = "20"
  }
  option {
    name  = "Node.js 22"
    value = "22"
  }
  option {
    name  = "Node.js 18 (LTS)"
    value = "18"
  }
}

# Agent
resource "coder_agent" "main" {
  arch           = data.coder_provisioner.me.arch
  os             = "linux"
  startup_script = <<-EOT
    set -e

    # Install Node.js via nvm
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

    nvm install ${data.coder_parameter.node_version.value}
    nvm use ${data.coder_parameter.node_version.value}

    # Install global tools
    npm install -g typescript ts-node pnpm

    # Clone repository if specified
    if [ -n "${data.coder_parameter.git_repo_url.value}" ]; then
      git clone --branch ${data.coder_parameter.git_branch.value} ${data.coder_parameter.git_repo_url.value} ~/project
      cd ~/project

      # Auto-detect and install dependencies
      if [ -f "pnpm-lock.yaml" ]; then
        pnpm install
      elif [ -f "yarn.lock" ]; then
        npm install -g yarn
        yarn install
      elif [ -f "bun.lockb" ]; then
        curl -fsSL https://bun.sh/install | bash
        export PATH="$HOME/.bun/bin:$PATH"
        bun install
      elif [ -f "package-lock.json" ] || [ -f "package.json" ]; then
        npm install
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
    "NODE_ENV=development",
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
