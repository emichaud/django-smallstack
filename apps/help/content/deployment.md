---
title: Deployment Overview
description: Understanding your deployment options
---

# Deployment Overview

Getting your Django application from your laptop to the internet can feel overwhelming. There are dozens of hosting providers, multiple deployment strategies, and countless configuration options. For someone just learning Django and reaching the point where they want to share their work with the world, this complexity can be a significant hurdle.

That's why {{ project_name }} includes ready-to-use configurations for two deployment approaches, each suited to different needs and experience levels.

## Why Two Approaches?

We provide configurations for both **Docker Compose** and **Kamal** because they serve different use cases:

| Approach | Best For | Complexity | Cost Structure |
|----------|----------|------------|----------------|
| Docker Compose | Maximum flexibility, any hosting provider | Medium | Varies by provider |
| Kamal | Solo developers, small teams, cost optimization | Lower | Fixed VPS cost |

## Docker Compose

The Docker Compose configuration included in this starter works with virtually any hosting service that supports containers:

- **AWS** (ECS, Fargate, Elastic Beanstalk)
- **Google Cloud Platform** (Cloud Run, GKE)
- **Digital Ocean** (App Platform, Droplets)
- **Azure** (Container Apps, AKS)
- **PythonAnywhere**, **Render**, **Railway**, and more

This is the **most versatile approach** and scales from simple hobby projects to enterprise deployments. If you're unsure which path to take, or if your organization already has container infrastructure, Docker Compose is the safe choice.

**[Read the Docker Deployment Guide](/help/docker-deployment/)**

## Kamal

Kamal is a deployment tool created by **David Heinemeier Hansson (DHH)**, the creator of Ruby on Rails. While it originated in the Rails ecosystem, Kamal deploys any containerized application—including Django.

**SSL certificates are free and automatic.** Kamal handles HTTPS via Let's Encrypt—your site is instantly secure with no configuration. Certificates renew automatically, so you never have to worry about expiration causing downtime.

Kamal shines for **solo developers and small teams** who want to:

- **Consolidate multiple applications** on a single VPS (or pool of VPS servers)
- **Minimize hosting costs** by maximizing server utilization
- **Achieve zero-downtime deployments** without complex orchestration
- **Keep things simple** with SSH-based deploys (no Kubernetes required)
- **Skip external registries** — images transfer directly via SSH from Docker Desktop

### How Kamal Achieves Zero-Downtime

A typical Kamal deployment takes **less than 60 seconds** and follows this process:

1. Build the new Docker image locally (requires Docker Desktop)
2. Transfer image to VPS via SSH tunnel (no external registry needed)
3. Start the new container
4. **Verify the new container is healthy** (via health check endpoint)
5. Only then, route traffic to the new container
6. Stop the old container

The key insight: **the old container keeps running until the new one is verified healthy**. This is the backbone of zero-downtime deployments.

### Kamal's Clever Proxy

Kamal includes `kamal-proxy`, a lightweight reverse proxy that manages routing to your containers. This proxy can:

- Handle multiple applications on a single server
- Automatically obtain and renew SSL certificates (Let's Encrypt)
- Route traffic based on domain names
- Manage health checks and container lifecycle

This makes it practical to run several small applications on one affordable VPS—a significant cost saver compared to dedicated hosting per application.

**[Read the Kamal Deployment Guide](/help/kamal-deployment/)**

## Which Should You Choose?

**Choose Docker Compose if:**
- You're deploying to managed container services (AWS, GCP, etc.)
- Your organization has existing container infrastructure
- You need maximum flexibility and portability
- You're building for enterprise scale

**Choose Kamal if:**
- You're a solo developer or small team
- You want to minimize hosting costs
- You prefer simple, SSH-based deployments
- You want to run multiple apps on shared infrastructure
- You have Docker Desktop running locally (required for builds)

## Database: SQLite by Default

{{ project_name }} uses **SQLite** as its default database—and that's intentional. For solo developers, small teams, and internal applications, SQLite is often the best choice:

- **Zero configuration** — No database server to manage
- **Zero cost** — No separate database service fees
- **Simple backups** — VPS snapshots include your database automatically
- **Production ready** — Handles thousands of requests per second

The database is stored in a `/data/` directory that persists across container rebuilds. Your data survives deployments.

**[Learn more about SQLite in production](/help/database-sqlite/)** | **[Upgrade to PostgreSQL](/help/database-postgresql/)**

## Getting Started

Both approaches use the same Dockerfile, so you can start with one and switch later if your needs change.

1. **[Docker Deployment Guide](/help/docker-deployment/)** — For local development and generic container hosting
2. **[Kamal Deployment Guide](/help/kamal-deployment/)** — For VPS deployment with zero-downtime updates
