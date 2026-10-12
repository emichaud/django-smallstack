---
title: Newsletter
order: 4
---

# Newsletter

Any blog can also be a newsletter. Readers subscribe, confirm by email, and
receive posts as issues.

Turn it on by editing the blog and ticking **Newsletter enabled**. A
*Subscribe* link then appears on the blog, and `/blog/<slug>/subscribe/` starts
accepting signups.

## Before your first send

Read this part. Everything below it is easy; this part is where newsletters
actually go wrong.

**Set your site URL.** Every issue contains an unsubscribe link built from it.
If it still resolves to `localhost`, every link in the send is dead — and a
send cannot be recalled. The app refuses to queue in that state; set
`SITE_DOMAIN` (or `SITE_URL`) first.

**Set up SPF, DKIM and DMARC for your sending domain.** No amount of code
substitutes for this. Without it a few thousand messages land in spam, and you
will not find out from any log — only from readers who never got it.

**Consider a separate mailer for bulk.** The *Mailer alias* field picks a
second entry from your `MAILERS` setting, so a 5,000-recipient send doesn't
share an IP and domain reputation with your password-reset emails.

**Send yourself a test copy.** It is the only way to catch a rendering or
header problem before subscribers see it.

## How subscribing works

1. A reader enters their address.
2. They get a confirmation email. **They are not subscribed yet.**
3. They click it, confirm, and receive a welcome email.

This is double opt-in, and it's on by default. It protects you from someone
signing up an address they don't own, and it is what keeps a list deliverable.

The signup page says the same thing whether or not an address is already
subscribed — otherwise the form becomes a way to test whether a given person
reads your blog.

## Sending an issue

From a post, use **Send as newsletter** — that creates a draft issue. Or create
one directly under **Blog → Issues** with its own subject and body.

On the issue page:

1. **Send test copy** to yourself.
2. **Send to subscribers** — this freezes the content and the audience, and
   starts delivery.

From that moment the issue is a permanent record: editing the post later does
not change what was sent, and the issue can no longer be edited.

Delivery runs in the background in batches. The page shows progress, and
**Stop sending** halts what hasn't gone out yet. Copies already delivered
cannot be recalled.

If some deliveries fail, **Retry failed deliveries** re-queues the ones worth
retrying. It never re-sends to anyone who already received it.

> Sending needs a worker running (`manage.py db_worker`). Without one, an issue
> sits at "queued" and nothing happens — `/smallstack/status/` reports it.

## Unsubscribing

Every issue carries a one-click unsubscribe button that mail clients show next
to the sender's name, plus a link in the footer. Both work without the reader
signing in, and the unsubscribe link in an old email keeps working forever.

Unsubscribing never deletes the record — that's how we remember someone opted
out, so a later list import can't quietly add them back.

## Bounces

If an address is rejected outright, it's suppressed and receives nothing
further. A temporary failure (a dropped connection, a greylist) is retried and
does **not** suppress anyone; only a run of consecutive failures eventually
does. Staff can clear a suppression under **Blog → Subscribers**.

## Importing a list

`manage.py blog_import_subscribers <blog> list.csv --consent-note "..."`

The consent note is required, because importing is the one path that skips
confirmation: you are asserting these people already agreed, and the record of
why needs to exist before the first send rather than be reconstructed
afterwards. Without `--confirmed`, imported addresses still have to confirm.

Don't import a list you bought, or addresses collected for something else. It
is the fastest way to get a sending domain blocked.
