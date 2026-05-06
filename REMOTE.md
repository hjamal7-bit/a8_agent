# Git Remote Setup for a8_agent

## Prerequisites

Before pushing to a remote repository, ensure you have:
- GitHub account (or other git hosting service)
- SSH keys configured (`~/.ssh/id_ed25519` or similar)
- SSH added to your GitHub account

## Setup Steps

### 1. Create Remote Repository

On GitHub:
1. Go to https://github.com/new
2. Repository name: `a8_agent`
3. Description: "A8 cadence draft generation and orchestration"
4. Choose: Public or Private (recommended: Private for sensitive CRM data)
5. Do NOT initialize with README, .gitignore, or license (we have our own)
6. Click "Create repository"
7. Copy the SSH URL: `git@github.com:YOUR_USERNAME/a8_agent.git`

### 2. Verify .gitignore

The project already has Python standards configured. Verify `/Users/jamal/code/a8_agent/.gitignore` includes:

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual Environment
venv/
env/
ENV/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# Environment
.env
.env.local
.env.*.local

# Logs
*.log
logs/

# Database
*.db
*.sqlite
*.sqlite3

# Temporary
tmp/
temp/
*.tmp
```

If `.gitignore` is missing, create it:

```bash
cat > /Users/jamal/code/a8_agent/.gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual Environment
venv/
env/
ENV/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# Environment
.env
.env.local
.env.*.local

# Logs
*.log
logs/

# Database
*.db
*.sqlite
*.sqlite3

# Temporary
tmp/
temp/
*.tmp
EOF
```

### 3. Verify Clean Git History

Check the current state:

```bash
cd /Users/jamal/code/a8_agent
git status
git log --oneline | head -10
```

The working tree should be clean. If there are uncommitted changes, commit them:

```bash
git add .
git commit -m "Final pre-remote commit"
```

### 4. Add Remote and Push

Replace `YOUR_USERNAME` with your GitHub username:

```bash
cd /Users/jamal/code/a8_agent

# Add the remote
git remote add origin git@github.com:YOUR_USERNAME/a8_agent.git

# Verify remote was added
git remote -v

# Push main branch to remote
git branch -M main
git push -u origin main
```

### 5. Verify Push

Confirm the repository is now on GitHub:
- Visit https://github.com/YOUR_USERNAME/a8_agent
- You should see all Python files, README, RUNBOOK, etc.

## Troubleshooting

### SSH Key Issues

If you get `Permission denied (publickey)`:

1. Check if SSH key exists: `ls -la ~/.ssh/id_*.pub`
2. If not, generate one: `ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519`
3. Add public key to GitHub: https://github.com/settings/keys
4. Test connection: `ssh -T git@github.com`

### Wrong Remote URL

If you added the wrong URL, remove and re-add:

```bash
git remote remove origin
git remote add origin git@github.com:YOUR_USERNAME/a8_agent.git
```

### HTTPS vs SSH

If you prefer HTTPS instead of SSH:

```bash
git remote add origin https://github.com/YOUR_USERNAME/a8_agent.git
git push -u origin main
```

(HTTPS will prompt for GitHub Personal Access Token)

## CI/CD (Optional)

Once remote is set up, consider adding GitHub Actions:
- Auto-run pytest tests on push
- Lint checks (black, ruff)
- Security scanning

Template: `.github/workflows/test.yml`

## References

- GitHub: https://docs.github.com/en/get-started/importing-your-project-to-github
- SSH Setup: https://docs.github.com/en/authentication/connecting-to-github-with-ssh
