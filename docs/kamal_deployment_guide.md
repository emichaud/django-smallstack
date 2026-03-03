# Kamal Deployment Guide for Django Projects

## Overview

Kamal (formerly MRSK) is a Docker-based deployment tool written in Ruby
that allows you to deploy containerized applications over SSH to remote
Linux servers.

Although Kamal is written in Ruby, it is language-agnostic in terms of
what it deploys. It works exceptionally well for Python/Django
applications that are containerized with Docker.

Kamal's core responsibilities:

-   Build Docker images
-   Push images to a container registry
-   Connect to servers via SSH
-   Orchestrate container lifecycle on remote Linux hosts
-   Manage zero-downtime deployments

------------------------------------------------------------------------

## Platform Support Summary

  --------------------------------------------------------------------------------
  Platform    Local Development Support  Production Target Support   Notes
  ----------- -------------------------- --------------------------- -------------
  macOS       ✅ Fully Supported         ✅ Linux Servers Only       Smoothest
                                                                     experience

  Linux       ✅ Fully Supported         ✅ Linux Servers Only       Ideal
                                                                     environment

  Windows     ⚠️ Possible but Not        ❌ Not Supported as Target  Expect
  (Native)    Recommended                                            friction

  Windows +   ✅ Recommended Setup       ✅ Linux Servers Only       Best Windows
  WSL2                                                               option
  --------------------------------------------------------------------------------

------------------------------------------------------------------------

## macOS

macOS is fully supported.

Requirements:

-   Ruby installed
-   Docker Desktop installed
-   SSH configured
-   Access to remote Linux server(s)

This is the most seamless environment for Kamal deployments.

------------------------------------------------------------------------

## Linux

Linux is fully supported and often the most stable setup.

Requirements:

-   Ruby
-   Docker
-   SSH access to servers

This is ideal for CI/CD systems and production-aligned workflows.

------------------------------------------------------------------------

## Windows (Native PowerShell / CMD)

Technically possible, but not ideal.

Common issues:

-   SSH agent forwarding inconsistencies
-   Docker path differences
-   Shell command assumptions in tooling
-   Ruby installation quirks

While you *can* make it work, it is not considered a smooth or
officially preferred path.

------------------------------------------------------------------------

## Windows with WSL2 (Recommended)

If using Windows, the recommended approach is:

-   Install WSL2
-   Use Ubuntu (or similar) inside WSL
-   Enable Docker Desktop WSL integration
-   Install Ruby and Kamal inside WSL

In this configuration, Kamal runs inside a Linux environment, making it
effectively equivalent to running on native Linux.

This setup is stable and production-aligned.

------------------------------------------------------------------------

## Production Server Requirements

Regardless of your local environment:

**Kamal deploys only to Linux servers.**

Your production servers must:

-   Run Linux
-   Have Docker installed
-   Allow SSH access
-   Support container execution

Kamal does not support deployment to:

-   Windows Server
-   macOS servers
-   Non-Docker environments

------------------------------------------------------------------------

## Why Kamal Works Well for Django

When using Django with Docker:

-   Kamal handles container orchestration
-   Gunicorn runs inside the container
-   Whitenoise can serve static files
-   Celery workers can be managed as additional services
-   PostgreSQL and Redis can be separate containers or managed services

Kamal provides:

-   Simple deployment commands
-   Rollback capability
-   Zero-downtime deploy patterns
-   Minimal infrastructure complexity

------------------------------------------------------------------------

## Recommended Workflow for Django + Kamal

1.  Containerize your Django project with Docker
2.  Configure gunicorn as the app server
3.  Use Docker Compose for local development
4.  Configure Kamal with:
    -   Registry credentials
    -   SSH host configuration
    -   Environment variables
5.  Deploy using: kamal deploy

------------------------------------------------------------------------

## Key Takeaways

-   Kamal is OS-flexible locally but Linux-only in production.
-   macOS and Linux are fully supported.
-   Windows users should use WSL2.
-   Kamal is a strong fit for Dockerized Django projects.
-   Keep production Linux-based for reliability and compatibility.

------------------------------------------------------------------------

## Strategic Perspective

Kamal shines when you want:

-   VPS-level control
-   Docker-based deployments
-   Simplicity without Kubernetes
-   Predictable, SSH-driven infrastructure

It is particularly well-suited for small to medium Django projects that
need clean, repeatable deployments without introducing Kubernetes-level
complexity.
