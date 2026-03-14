# Welcome

You made it — nice. This is your project's documentation home, and everything you need is right here.

SmallStack gives you a fully themed Django starter with authentication, dark mode, activity tracking, database backups, background tasks, and a help system (you're looking at it). The goal is simple: clone it, customize it, ship it.

## Where to Start

**Brand new?** Start with the quick setup guide — it walks you through the first things to configure after cloning:

- [Getting Started](/help/getting-started/) — First-run setup, branding, creating pages, and deployment basics
- [Quick Setup (TL;DR)](/help/quick-setup/) — Clone to deploy in 8 steps

**Ready to build?** Jump into the reference docs:

- [SmallStack Reference](/smallstack/help/smallstack/) — The full documentation covering every feature, component, and configuration option

## What's Included

Here's what works out of the box with zero extra configuration:

| Feature | What It Does |
|---------|-------------|
| **Authentication** | Login, signup, password reset — all themed and ready |
| **User Profiles** | Photo, bio, timezone, color palette preference |
| **Dark/Light Mode** | 5 color palettes, user-selectable from the topbar |
| **Activity Tracking** | Request logging with a staff dashboard |
| **Database Backups** | On-demand + scheduled, with email alerts |
| **Background Tasks** | Django's built-in task framework, no Redis needed |
| **Help System** | Markdown docs with search — you're reading it now |
| **Model Explorer** | Auto-generated CRUD from your admin registrations |

## Adding Your Own Docs

This help system is yours to extend. Add project-specific documentation right alongside the SmallStack reference:

1. Create a `.md` file in `apps/help/content/`
2. Add it to `apps/help/content/_config.yaml` under your section's pages
3. It appears at `/help/your-page-slug/`

You can organize docs into sections, add your own icons, and even create separate documentation areas for different parts of your project. See [Using the Help System](/smallstack/help/smallstack/help-system/) for the full guide.

## Quick Links

- [Starter Page](/starter/) — See all UI components in action
- [Layout Gallery](/smallstack/layouts/) — Preview sidebar + topbar combinations
- [Theming Guide](/smallstack/help/smallstack/theming/) — Colors, dark mode, custom palettes
- [FAQ](/smallstack/help/smallstack/faq/) — Common questions answered
