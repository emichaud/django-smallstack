---
title: Playlists
order: 3
---

# Playlists

A playlist shows dashboards and [goal lists](/smallstack/help/dashboards/goals/) one after another. Page through them yourself,
like slides in a meeting, or let them rotate on a timer on a screen on the wall.

Find them under **Dashboards → Playlists**.

## Making one

1. Choose **New playlist** and give it a name.
2. Under **Playing**, set the show's defaults: the **seconds on each slide**,
   whether it **loops** and whether it **plays when opened**.
3. Under **Slides, in order**, pick a dashboard or goal list and choose **Add**.
   Repeat for each one. Use ↑ and ↓ to reorder, and ✕ to remove.
4. Each slide shows for the default seconds and says **Default**. Click that to
   give one slide its own time (− and + adjust it); **↺** puts it back on the
   default. You can also pin a slide to a period (say, *last 7 days*) for this
   playlist only.

Clicking a column heading sorts the slides by that column. The rows are the order
the slides play in, so sorting changes the play order. **Undo** puts the previous
order back, and nothing changes until you save. Columns can be dragged wider or
narrower.

A personal playlist can hold your own dashboards and goal lists, and shared ones. A
shared playlist can hold only shared ones. Anyone watching sees only the slides
they're allowed to open; the others are skipped.

## Playing it

The bar at the top has previous, play/pause and next, the name of the dashboard
on screen, and one step per dashboard. The current step fills as its time runs
out, and you can click any step to jump to it.

| Key | Does |
|---|---|
| → or Page Down | Next dashboard |
| ← or Page Up | Previous dashboard |
| Space or K | Play or pause |
| Home / End | First / last dashboard |
| F | Full screen |

The player pauses by itself when you switch to another tab, and carries on when
you come back. Clicking into a card, to read its rows, pauses it too.

## Links that control it

The address follows along as it plays, so a copied link opens on the same
dashboard. You can also add these to a playlist's address:

| Add | Does |
|---|---|
| `?play=1` | Start playing. `?play=0` opens paused. |
| `?slide=3` | Open on the third dashboard. |
| `?seconds=20` | Show each dashboard for 20 seconds, this time only. |
| `?loop=0` | Stop at the last dashboard instead of starting over. |
| `?kiosk=1` | Hide the site's menus, for a wall screen. |

Combine them with `&`: **Wall screen** on a playlist's page opens
`?kiosk=1&play=1`, which is the link to put on a TV.

## Renaming and deleting dashboards

A playlist keeps up with its dashboards. If one is renamed, the playlist follows
it. If one is deleted, it leaves the playlist.
