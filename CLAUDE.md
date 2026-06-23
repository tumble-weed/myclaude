# myclaude — personal Claude config source of truth

This repo is the **version-controlled source**
for my personal Claude Code config (commands,
output styles, skills). The live files under
`~/.claude/` are **symlinks back into this repo**,
created by `manage.py`. Editing here changes the
live config immediately, and vice versa.

## The rule that matters

**Never write a new file directly into
`~/.claude/<category>/`.** It works on this
machine but is invisible to git — not tracked, not
synced, lost on reinstall.

To add anything (a command, output style, skill):
1. Create the real file under
   `installables/<category>/<name>`.
2. Run `python manage.py install` to symlink it
   into `~/.claude/<category>/<name>`.

To edit an existing live file, follow the symlink
to its `installables/` target and edit there (the
Write/Edit tools refuse to write through a
symlink, which is the signal you're in the wrong
place).

Before adding to any dir under `~/.claude/`,
`ls -la` it first — most entries are symlinks into
this repo.

## Layout

```
installables/<category>/<name>   # real files, git-tracked
  commands/        # slash commands (*.md)
  output-styles/   # e.g. no-bs.md
  skills/          # skill dirs (draw-it, grill-me, ...)
manage.py          # symlink installer
mattpocock-skills/ # vendored external skills (gitignored, not installed)
```

`category` = the subdir name under `~/.claude/`
(commands, output-styles, skills, ...). Add a new
category just by making the dir under
`installables/`.

## manage.py

Symlinks every `installables/<category>/<name>` to
`~/.claude/<category>/<name>` with absolute paths.

```
python manage.py install      # link all; aborts on clashes
python manage.py install --allow-partial-install   # skip clashes
python manage.py reinstall    # link only missing ones
python manage.py uninstall    # remove only our symlinks
python manage.py <cmd> --dry-run        # preview
python manage.py <cmd> --claude-dir DIR # target a different config dir
```

Only touches symlinks that point back here —
foreign symlinks and real files are left alone.

## Feedback-command family

Terse `/`-commands for correcting my output mid-
chat (all in `installables/commands/`):
`/stfu` (follow output format), `/tmj` (re-explain
with example + code), `/split` (multiple themes
bundled — break apart), `/brief` (one theme but
too wordy/repetitive — trim), `/src`
(verify claim against the code), `/slow` (stop,
confirm before acting), `/wide` (lines wider than
~40 cols).
