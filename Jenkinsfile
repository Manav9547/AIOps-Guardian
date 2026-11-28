// AIOps Guardian pipeline (commit 14: checkout, lint, test).
//
// Every stage calls a make target, so any stage can be run by hand when
// debugging. Later commits add the remaining stages of the guide's pipeline:
//   Train model (48) · Build images (15) · Push images (15, creds from Vault 25)
//   Blocked tag? (41) · Deploy booking (21) · Deploy guardian (39) · Smoke test (32)

pipeline {
    agent any

    options {
        skipDefaultCheckout()          // checkout is its own visible stage below
        timestamps()
        timeout(time: 20, unit: 'MINUTES')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        // Each build gets its own compose project, so CI never shares (or deletes)
        // the dev stack's containers and database on the same machine.
        COMPOSE_PROJECT_NAME = "aiops-ci-${env.BUILD_NUMBER}"
        // Docker picks a free host port for CI Postgres: no clash with a dev one on 5432.
        POSTGRES_PORT = '0'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                sh 'git log -1 --format="Building %h by %an: %s"'
            }
        }

        stage('Lint') {
            steps {
                sh 'make lint'
            }
        }

        stage('Test') {
            steps {
                sh 'make test'
            }
        }
    }

    post {
        always {
            // Remove this build's test Postgres and its volume (guarded to aiops-ci-* only).
            sh 'make ci-clean || true'
        }
        cleanup {
            cleanWs()
        }
    }
}
