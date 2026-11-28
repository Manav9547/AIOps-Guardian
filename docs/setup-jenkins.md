# Jenkins setup

How to install Jenkins and run the AIOps Guardian pipeline from a fresh
machine. Following this page alone should give you a green build of `main`.

The automatic trigger on every push (smee.io webhook) is in
[setup-webhook.md](setup-webhook.md) (commit 16). Docker Hub credentials are
added in commit 15.

## Contents

1. [Why a native install](#1-why-a-native-install)
2. [Versions](#2-versions)
3. [Install Jenkins](#3-install-jenkins)
4. [Give Jenkins access to Docker](#4-give-jenkins-access-to-docker)
5. [First login and plugins](#5-first-login-and-plugins)
6. [Create the pipeline job](#6-create-the-pipeline-job)
7. [First build](#7-first-build)
8. [How the pipeline runs](#8-how-the-pipeline-runs)
9. [Troubleshooting](#9-troubleshooting)

## 1. Why a native install

Install Jenkins **directly on the machine** (apt, Homebrew, or WSL2), not
as a Docker container.

`make lint` and `make test` start containers that mount the job's workspace
(`./:/src`). A Jenkins container talking to the host's Docker daemon would ask
Docker to mount a path that only exists inside the Jenkins container, and the
tests would see an empty folder. With a native install the workspace is a real
folder on the host, so the mounts just work.

## 2. Versions

Tested on this setup. Use the same Jenkins LTS line if you can.

| Tool | Version tested | Check with |
|---|---|---|
| Jenkins LTS | 2.580.2 | footer of the Jenkins web UI |
| Java | 21 (OpenJDK) | `java -version` |
| Docker Engine + Compose plugin | 29.x / 2.40 | `docker --version`, `docker compose version` |
| GNU Make | 4.x | `make --version` |
| Git | 2.x | `git --version` |

Jenkins itself needs about 1 GB of RAM. Each build adds a Python container and
a Postgres container for a minute or two.

## 3. Install Jenkins

### Ubuntu / Debian (what this project was tested on)

```bash
# Java 21 and fonts Jenkins needs
sudo apt update
sudo apt install -y fontconfig openjdk-21-jre make git

# Jenkins LTS ("stable") repository
sudo wget -O /usr/share/keyrings/jenkins-keyring.asc \
  https://pkg.jenkins.io/debian-stable/jenkins.io-2023.key
echo "deb [signed-by=/usr/share/keyrings/jenkins-keyring.asc] https://pkg.jenkins.io/debian-stable binary/" \
  | sudo tee /etc/apt/sources.list.d/jenkins.list > /dev/null
sudo apt update
sudo apt install -y jenkins

sudo systemctl enable --now jenkins
systemctl is-active jenkins          # -> active
```

If `apt update` complains about the key, Jenkins has rotated its signing key:
take the current key URL from <https://www.jenkins.io/doc/book/installing/linux/>
and repeat the `wget` line.

Docker must already be installed: Docker Engine with the Compose plugin
(`docker compose version` must work).

### macOS

```bash
brew install openjdk@21 jenkins-lts
brew services start jenkins-lts
```

- Install **Docker Desktop** and start it.
- `make` and `git` come with the Xcode command line tools: `xcode-select --install`.
- Jenkins runs as your user, so it can already use Docker. Skip section 4,
  but see "docker: not found" in [Troubleshooting](#9-troubleshooting):
  Homebrew's folder is often missing from Jenkins' `PATH`.

### Windows

Use **WSL2 with Ubuntu** and follow the Ubuntu steps inside WSL.

- Turn on systemd in WSL: put these lines in `/etc/wsl.conf`, then run
  `wsl --shutdown` in PowerShell and reopen Ubuntu:
  ```ini
  [boot]
  systemd=true
  ```
- In Docker Desktop, go to **Settings → Resources → WSL integration** and enable your Ubuntu distro.
- Open Jenkins from Windows at <http://localhost:8080>.

## 4. Give Jenkins access to Docker

*Linux and WSL only.* The Jenkins service runs as its own `jenkins` user,
which needs to be in the `docker` group:

```bash
sudo usermod -aG docker jenkins
sudo systemctl restart jenkins       # group changes apply only after a restart

# check: all three must work as the jenkins user
sudo -u jenkins docker ps
sudo -u jenkins docker compose version
sudo -u jenkins make --version
```

Without this, every build fails at the **Lint** stage with
`permission denied ... /var/run/docker.sock`.

> Being in the `docker` group is effectively root access on that machine.
> Fine for a local dev box; do not expose this Jenkins to the internet.

## 5. First login and plugins

1. Open <http://localhost:8080>.
2. Paste the unlock password:
   ```bash
   sudo cat /var/lib/jenkins/secrets/initialAdminPassword
   ```
   (macOS: `cat ~/.jenkins/secrets/initialAdminPassword`)
3. Choose **Install suggested plugins**.
4. Create **your own** admin user. Each member uses their own Jenkins and
   their own account; never share passwords. If someone needs your
   Jenkins, create them a separate user under **Manage Jenkins → Users**.
5. Keep the Jenkins URL as `http://localhost:8080/`.

Then check that these plugins are installed (**Manage Jenkins → Plugins →
Installed plugins**). Most come with the suggested set. Install any that are missing
from **Available plugins** and restart Jenkins.

| Plugin | ID | Tested | Used for |
|---|---|---|---|
| Pipeline | `workflow-aggregator` | 608.v67378e9d3db_1 | Jenkinsfile pipelines |
| Pipeline: Declarative | `pipeline-model-definition` | 2.2293.v6e7193cec599 | `pipeline { ... }` syntax |
| Git | `git` | 5.11.0 | `checkout scm` |
| GitHub | `github` | 1.47.0 | push trigger (commit 16) |
| Credentials Binding | `credentials-binding` | 728.v902a_273b_8947 | Docker Hub login (commit 15) |
| Timestamper | `timestamper` | 1.30 | `timestamps()` in the log |
| Workspace Cleanup | `ws-cleanup` | 0.49 | `cleanWs()` after each build |

## 6. Create the pipeline job

1. **New Item** → name `aiops-guardian` → **Pipeline** → **OK**.
2. Leave **General** and **Triggers** as they are. The Jenkinsfile itself
   sets the build history (last 20), no parallel builds, and the timeout.
3. In the **Pipeline** section:

   | Field | Value |
   |---|---|
   | Definition | Pipeline script from SCM |
   | SCM | Git |
   | Repository URL | `https://github.com/Manav9547/AIOps-Guardian.git` |
   | Credentials | *none* (public repo). If the repo is made private: **Add → Username with password**, your GitHub username and a personal access token with read access to the repo |
   | Branch Specifier | `*/main` |
   | Script Path | `Jenkinsfile` |
   | Lightweight checkout | ticked (default) |

4. **Save**.

To try a pipeline change before merging it, temporarily set **Branch
Specifier** to your branch (e.g. `*/b/p2-docker-push`), build, then set it
back to `*/main`.

## 7. First build

Click **Build Now**, open the build, then **Console Output**. A good
build contains these lines (from the first real build of this project):

```
[2026-11-28T16:48:48.181Z] Building 40539d8 by Manav9547: Merge pull request #12 from Manav9547/a/p2-jenkinsfile
[2026-11-28T16:49:43.249Z] All checks passed!
[2026-11-28T16:50:14.132Z] ============================== 95 passed in 9.92s ==============================
Finished: SUCCESS
```

The first line is from Checkout, the second from Lint and the third from Test.
The test count grows as tests are added. The first build takes a few minutes
because it builds the test image. Later builds reuse Docker's cache.

**Check that failures are caught.** On a throwaway branch, add a failing test:

```python
# app/tests/test_zz_broken.py
def test_deliberately_broken():
    assert 1 == 2
```

Point the job at that branch and build. It must stop red at **Test**
(`1 failed`, `Finished: FAILURE`). Delete the branch afterwards and never merge it.

## 8. How the pipeline runs

Every stage only calls a `make` target, so you can run any stage by hand on
your own machine (`make lint`, `make test`) to debug it.

| Stage | Runs | What it does |
|---|---|---|
| Checkout | `checkout scm` | clones the commit being built |
| Lint | `make lint` | ruff in the test image (rules in `ruff.toml`), no database |
| Test | `make test` | pytest in the test image against a throwaway Postgres |
| *(always)* | `make ci-clean`, `cleanWs()` | removes this build's containers, volume and workspace |

**CI never touches your dev stack.** The Jenkinsfile sets, for every build:

- `COMPOSE_PROJECT_NAME=aiops-ci-<build number>`: its own containers,
  network and database volume, separate from `make dev-up`'s `aiops-dev`;
- `POSTGRES_PORT=0`: Docker picks a free host port, so CI's Postgres does not
  clash with a dev Postgres already on 5432.

`make ci-clean` refuses to run unless `COMPOSE_PROJECT_NAME` starts with
`aiops-ci-`, so it can never delete the dev database, even when run by hand.

Later phases add stages (build and push images, deploy, smoke test). See the
comment at the top of the `Jenkinsfile`.

## 9. Troubleshooting

| Symptom in Console Output | Cause | Fix |
|---|---|---|
| `permission denied while trying to connect to the Docker daemon socket` | `jenkins` user not in the `docker` group, or Jenkins not restarted since | Section 4, then `sudo systemctl restart jenkins` |
| `docker: not found` / `make: not found` | Jenkins' `PATH` lacks the tool (common on macOS with Homebrew) | **Manage Jenkins → System → Global properties → Environment variables**: name `PATH+EXTRA`, value `/opt/homebrew/bin:/usr/local/bin` (Intel Macs: `/usr/local/bin`) |
| `unknown shorthand flag: 'f' in -f` or `docker: 'compose' is not a docker command` | Docker Compose v2 missing | Linux: `sudo apt install docker-compose-v2` (Ubuntu's Docker packages) or `docker-compose-plugin` (Docker's own repo); macOS/Windows: update Docker Desktop |
| `No such DSL method 'timestamps'` or `'cleanWs'` | Plugin missing | Install Timestamper / Workspace Cleanup (section 5) |
| `Couldn't find any revision to build` | Branch Specifier does not match a branch | Use `*/main` (note the `*/`) |
| `Authentication failed` / `Repository not found` | Repo is private | Add GitHub credentials (section 6) |
| Test stage fails with database connection errors (e.g. `could not translate host name "postgres"`) | The test Postgres did not start (`make test` sets `REQUIRE_DB=1`, so DB tests fail rather than skip) | Run `make test` by hand in a checkout to see the compose error; check Docker has free disk space (`docker system df`) |
| Build hangs at **Test** and is aborted after 20 min | Postgres never became healthy | `docker ps -a \| grep aiops-ci`, then `docker logs <container>` |
| Port 8080 already in use | Something else on 8080 | Set `JENKINS_PORT` with `sudo systemctl edit jenkins` (`[Service]` + `Environment="JENKINS_PORT=8081"`), then restart |

Leftover CI containers from an aborted build can be removed by hand. Use the
build number from the job page:

```bash
COMPOSE_PROJECT_NAME=aiops-ci-<build number> make ci-clean
```
