# Scene reference

Every built-in scene and every parameter it takes. **Generated** by
`tools/gendocs.py` from the scene registry — edit the `Param(...)` declarations
in `glance/scenes/*.py`, not this file, then run:

```bash
python tools/gendocs.py
```

A test fails if this file drifts from the code.

Each scene is used the same way, in a channel:

```yaml
channels:
  main:
    - scene: <id>
      params: { ... }
      takeover: false       # pre-empt the rotation while available
      when: {}              # months, weekdays, hours, dates, from/to, mode
      dwell: 0              # seconds to hold before advancing
      enabled: true
```

You can also render one directly, which is how the preview page does it:

```
/s/<id>.png?param=value
```

## Every scene accepts

| Param | Type | Default | Means |
|---|---|---|---|
| `always` | bool | `false` | Stay in the rotation even with nothing to show. |

## Scenes

| Scene | Shows |
|---|---|
| [`activity`](#activity) | Which zone saw movement, and how long ago |
| [`agenda`](#agenda) | Next calendar event(s) |
| [`alignment`](#alignment) | Test card: are the top and bottom rows reaching the panel? |
| [`banner`](#banner) | A welcome banner -- title, subtitle, evergreens |
| [`baseball`](#baseball) | Last result and next game for the teams you follow |
| [`blank`](#blank) | An intentionally dark panel |
| [`clock`](#clock) | Time and date |
| [`columns`](#columns) | Three columns of upcoming events, packed by day |
| [`countdown`](#countdown) | Days remaining until a date or a season |
| [`date`](#date) | Day and date, no clock |
| [`entities`](#entities) | Home Assistant entity states |
| [`holiday`](#holiday) | The currently active holiday |
| [`instagram`](#instagram) | Follower and post counts for an Instagram account |
| [`language`](#language) | A word or phrase in another language, and what it means |
| [`panels`](#panels) | Test card: shows the physical 64px modules |
| [`pulse`](#pulse) | Names in a colour, over time or across the letters |
| [`rankings`](#rankings) | The top of a poll, as many as fit |
| [`reminders`](#reminders) | Open reminders |
| [`scores`](#scores) | Score and next fixture from a configured scoreboard |
| [`sky`](#sky) | Sun and moon crossing the sky, with the real phase |
| [`sprite`](#sprite) | Text with a pixel-art sprite set into it |
| [`sprites`](#sprites) | Every sprite, for checking the art |
| [`static`](#static) | A PNG file from assets/static/ |
| [`text`](#text) | Fixed text from the channel config |
| [`today-agenda`](#today-agenda) | What is left on today's calendar |
| [`todos`](#todos) | Open items from the reminders file |
| [`weather`](#weather) | Current conditions |

### `activity`

Which zone saw movement, and how long ago

| Param | Type | Default | Means |
|---|---|---|---|
| `entities` | text | — | Leave blank to use every motion sensor you have. |
| `device_class` | text | `motion` | Which class to gather when entities is blank. |
| `count` | number | `4` | How many entities to show. (min 1, max 4) |
| `title` | text | — | Header line. |
| `accent` | color | `teal` | One of: any palette colour or `#rrggbb`. |
| `alert` | color | `amber` | Colour for a zone that is active right now. One of: any palette colour or `#rrggbb`. |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |

### `agenda`

Next calendar event(s)

| Param | Type | Default | Means |
|---|---|---|---|
| `calendar` | select | — | Which feed, or blank for all. Comma-separate for several. One of: a calendar named under `sources.calendars`. |
| `count` | number | `1` | 1 draws the hero layout; 2-3 stack as a list. (min 1, max 3) |
| `today` | bool | `false` | Only what is left today. |
| `hour24` | bool | `false` | 24-hour clock. |
| `lookahead_days` | number | `14` | How far ahead to look for events. (min 1, max 90) |
| `accent` | color | `amber` | One of: any palette colour or `#rrggbb`. |
| `time_color` | color | — | The time, drawn apart from the title; defaults to the accent. One of: any palette colour or `#rrggbb`. |
| `location` | bool | `true` | Show the location under the title. |
| `empty` | text | — | What to say when there is nothing. |

### `alignment`

Test card: are the top and bottom rows reaching the panel?

Takes no parameters of its own.

### `banner`

A welcome banner -- title, subtitle, evergreens

| Param | Type | Default | Means |
|---|---|---|---|
| `title` | text | `WELCOME` | The big line. |
| `subtitle` | text | — | The small line under it. |
| `color` | color | `white` | One of: any palette colour or `#rrggbb`. |
| `accent` | color | `mint` | One of: any palette colour or `#rrggbb`. |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |
| `motif` | select | `trees` | Evergreens either side, plain rules, or nothing. One of: `trees`, `rules`, `none`. |
| `scale` | number | `0` | Title size; 0 fits the widest that will go. (min 0, max 3) |
| `span` | number | `1` | Lay the banner out across this many panels. (min 1, max 2) |
| `part` | number | `1` | Which slice of a spanned banner this channel serves. (min 1, max 2) |

### `baseball`

Last result and next game for the teams you follow

| Param | Type | Default | Means |
|---|---|---|---|
| `accent` | color | `sky` | Highlight for the team you follow. One of: any palette colour or `#rrggbb`. |
| `broadcast` | bool | `true` | Show where to watch. |
| `record` | bool | `true` | Show the W-L record. |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |

### `blank`

An intentionally dark panel

| Param | Type | Default | Means |
|---|---|---|---|
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |

### `clock`

Time and date

| Param | Type | Default | Means |
|---|---|---|---|
| `hour24` | bool | `false` | 24-hour clock. |
| `date` | bool | `true` | Show the date line. |
| `lead` | number | `0` | Seconds to shift forward; set to half your refresh interval so the error is centred rather than always slow. (min 0, max 900) |
| `color` | color | `white` | One of: any palette colour or `#rrggbb`. |
| `accent` | color | `sky` | One of: any palette colour or `#rrggbb`. |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |

### `columns`

Three columns of upcoming events, packed by day

| Param | Type | Default | Means |
|---|---|---|---|
| `calendar` | select | — | Which feed, or blank for all. One of: a calendar named under `sources.calendars`. |
| `columns` | number | `3` | How many day columns across the strip. (min 1, max 6) |
| `skip_columns` | number | `0` | Start this many columns in. Pair two panels with 0 and 3 and they run continuously, whatever the packing. (min 0, max 9) |
| `days` | number | — | Distinct days to consider; defaults to the column count. (min 1, max 12) |
| `hour24` | bool | `false` | 24-hour clock. |
| `wrap` | bool | `true` | Let a long title use a second row, but only when no event would be pushed off the column. |
| `accent` | color | `amber` | One of: any palette colour or `#rrggbb`. |
| `time_color` | color | — | The time, drawn apart from the title; defaults to the accent. One of: any palette colour or `#rrggbb`. |
| `from_days` | number | `0` | Start this many days ahead. 0 is today; 3 skips the near term a companion panel already covers. (min 0, max 30) |
| `lookahead_days` | number | `14` | How far ahead to look for events. (min 1, max 90) |

### `countdown`

Days remaining until a date or a season

| Param | Type | Default | Means |
|---|---|---|---|
| `date` | text | — | YYYY-MM-DD for a one-off, or MM-DD to repeat yearly. |
| `season` | select | — | Count to the real equinox or solstice instead of a date. One of: ``, `spring`, `summer`, `autumn`, `fall`, `winter`. |
| `hemisphere` | select | `north` | Which half of the planet the season belongs to. One of: `north`, `south`. |
| `meteorological` | bool | `false` | Use the 1st of the month rather than the astronomical moment. |
| `motif` | select | `none` | Decoration around the number; leaves for autumn. One of: `none`, `leaves`. |
| `gradient_to` | color | — | Ramp the number from `color` to this across its digits. One of: any palette colour or `#rrggbb`. |
| `within` | number | `0` | Only appear when the target is this many days off; 0 shows it always. (min 0, max 400) |
| `label` | text | — | What it is counting to. |
| `color` | color | `amber` | One of: any palette colour or `#rrggbb`. |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |

### `date`

Day and date, no clock

| Param | Type | Default | Means |
|---|---|---|---|
| `year` | bool | `true` | Include the year. |
| `rule` | bool | `true` | Hairline along the bottom. |
| `color` | color | `white` | One of: any palette colour or `#rrggbb`. |
| `accent` | color | `sky` | One of: any palette colour or `#rrggbb`. |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |

### `entities`

Home Assistant entity states

| Param | Type | Default | Means |
|---|---|---|---|
| `entities` | text | — | entity_id list, comma separated. Add =Label to shorten a long name for the panel. |
| `layout` | select | `columns` | columns: up to 3 side by side. rows: up to 4 stacked. One of: `columns`, `rows`. |
| `title` | text | — | Header line, rows layout only. |
| `accent` | color | `teal` | One of: any palette colour or `#rrggbb`. |
| `alert` | color | `red` | Colour for a low battery or an open door. One of: any palette colour or `#rrggbb`. |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |

### `holiday`

The currently active holiday

| Param | Type | Default | Means |
|---|---|---|---|
| `name` | text | — | Pin to one holiday by name or slug. |
| `index` | number | `0` | Which one, when several are active at once. (min 0) |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |

### `instagram`

Follower and post counts for an Instagram account

| Param | Type | Default | Means |
|---|---|---|---|
| `handle` | text | — | Shown as the title; defaults to the configured account. |
| `accent` | color | `magenta` | One of: any palette colour or `#rrggbb`. |
| `color` | color | `white` | One of: any palette colour or `#rrggbb`. |
| `stale_after` | number | `21600` | Seconds before the age is shown as a warning. (min 0) |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |

### `language`

A word or phrase in another language, and what it means

| Param | Type | Default | Means |
|---|---|---|---|
| `language` | select | — | Which deck: es, fr, or whatever you add. One of: a deck in `config/vocabulary/`. |
| `rotate` | number | `900` | Seconds each word holds before the next one. (min 30, max 86400) |
| `shuffle` | bool | `true` | Reshuffle the deck daily rather than run it in order. |
| `reveal` | number | `0` | Hide the meaning until this far through the slot; 0 shows it throughout. (min 0, max 1) |
| `color` | color | `white` | One of: any palette colour or `#rrggbb`. |
| `article_color` | color | `amber` | The gender-carrying article, drawn apart. One of: any palette colour or `#rrggbb`. |
| `gloss_color` | color | `sky` | One of: any palette colour or `#rrggbb`. |
| `feminine_color` | color | — | Optional second article colour, for feminine nouns. One of: any palette colour or `#rrggbb`. |
| `note` | bool | `true` | Show the pronunciation hint. |
| `label` | bool | `false` | Name the language. |
| `margin` | number | `8` | Blank kept at each edge, so the pane separates from its neighbours as the device pans past. (min 0, max 40) |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |

### `panels`

Test card: shows the physical 64px modules

| Param | Type | Default | Means |
|---|---|---|---|
| `module` | number | `64` | Module width; 64 unless your hardware is unusual. (min 8, max 192) |

### `pulse`

Names in a colour, over time or across the letters

| Param | Type | Default | Means |
|---|---|---|---|
| `items` | text | `ADA:amber,GRACE:sky` | NAME:colour, comma separated. |
| `mode` | select | `gradient` | gradient ramps across the letters; pulse animates (this panel does not decode APNG). One of: `gradient`, `pulse`. |
| `layout` | select | `column` | Stack the names, or set them side by side. One of: `column`, `row`. |
| `from` | color | `white` | Colour each name starts at. One of: any palette colour or `#rrggbb`. |
| `font` | select | `5x7` | Typeface for the names. One of: `5x7`, `3x5`, `5x7mono`. |
| `scale` | number | — | Text size; blank fits the largest that will go. (min 1, max 4) |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |

### `rankings`

The top of a poll, as many as fit

| Param | Type | Default | Means |
|---|---|---|---|
| `board` | select | — | Which configured scoreboard's poll to read. One of: a board named under `sources.scoreboards`. |
| `count` | number | `0` | How many to show; 0 fits as many as the strip takes. (min 0, max 25) |
| `style` | select | `crests` | Team crests, or rank and abbreviation as text. One of: `crests`, `text`. |
| `accent` | color | `amber` | One of: any palette colour or `#rrggbb`. |
| `label` | bool | `true` | Name the poll. |
| `margin` | number | `8` | Blank kept at each edge, so the pane separates from its neighbours as the device pans past. (min 0, max 40) |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |

### `reminders`

Open reminders

| Param | Type | Default | Means |
|---|---|---|---|
| `count` | number | `3` | How many rows. (min 1, max 4) |
| `style` | select | `list` | hero draws only the most pressing one, large. One of: `list`, `hero`. |
| `header` | bool | `true` | Show the title bar and count. |
| `title` | text | `REMINDERS` | Header text. |
| `accent` | color | `sky` | One of: any palette colour or `#rrggbb`. |
| `tag` | text | — | Only items with this tag. |

### `scores`

Score and next fixture from a configured scoreboard

| Param | Type | Default | Means |
|---|---|---|---|
| `board` | select | — | Which configured scoreboard to read. One of: a board named under `sources.scoreboards`. |
| `accent` | color | `amber` | One of: any palette colour or `#rrggbb`. |
| `label` | bool | `true` | Show the league name. |
| `broadcast` | bool | `true` | Show where to watch. |
| `rank` | bool | `true` | Show poll rankings where there are any. |
| `logos` | bool | `true` | Draw team logos when they read at this size. |
| `crest` | number | `14` | Crest size on the scoreline. (min 8, max 24) |
| `names` | bool | `true` | Short team names under the scores. |
| `today_color` | color | `green` | Colour for TODAY on the next-fixture line. One of: any palette colour or `#rrggbb`. |
| `margin` | number | `8` | Blank kept at each edge, so the pane separates from its neighbours as the device pans past. (min 0, max 40) |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |

### `sky`

Sun and moon crossing the sky, with the real phase

| Param | Type | Default | Means |
|---|---|---|---|
| `times` | bool | `true` | Sunrise and sunset in the corners. |
| `label` | bool | `true` | Name the moon phase at night. |
| `date` | select | `sky` | Where the date sits, or none to leave it out. One of: `sky`, `horizon`, `ground`, `none`. |
| `weather` | bool | `true` | Cloud, rain and fog from the current conditions. |
| `texture` | bool | `true` | Draw the moon's dark plains. |
| `stars` | number | `26` | Stars at night; cloud cover thins them. (min 0, max 80) |

### `sprite`

Text with a pixel-art sprite set into it

| Param | Type | Default | Means |
|---|---|---|---|
| `before` | text | — | Text to the left of the art. |
| `after` | text | — | Text to the right. |
| `sprite` | select | `sweatpants` | Which piece of pixel art to set in the line. One of: any sprite in `glance/sprites.py`. |
| `color` | color | `white` | The text; the sprite keeps its own palette. One of: any palette colour or `#rrggbb`. |
| `font` | select | `5x7` | Typeface for the surrounding words. One of: `5x7`, `3x5`, `5x7mono`. |
| `gap` | number | `5` | Pixels between art and text. (min 0, max 40) |
| `scale` | number | `4` | Ceiling on text size, not a fixed size. (min 1, max 4) |
| `sprite_scale` | number | `1` | Whole-number multiplier on the art. (min 1, max 4) |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |

### `sprites`

Every sprite, for checking the art

Takes no parameters of its own.

### `static`

A PNG file from assets/static/

| Param | Type | Default | Means |
|---|---|---|---|
| `name` | select | — | Which file. One of: a PNG in `assets/static/`. |
| `align` | select | `center` | Where the image sits if it is narrower than the strip. One of: `left`, `center`, `right`. |
| `valign` | select | `middle` | Where the image sits if it is shorter than 32px. One of: `top`, `middle`, `bottom`. |
| `caption` | text | — | Text bar along the bottom. |
| `caption_color` | color | `white` | One of: any palette colour or `#rrggbb`. |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |

### `text`

Fixed text from the channel config

| Param | Type | Default | Means |
|---|---|---|---|
| `text` | text | — | The main line. |
| `sub` | text | — | Smaller line beneath. |
| `color` | color | `white` | One of: any palette colour or `#rrggbb`. |
| `sub_color` | color | — | One of: any palette colour or `#rrggbb`. |
| `font` | select | `5x7` | Typeface for the body text. One of: `5x7`, `3x5`, `5x7mono`. |
| `scale` | number | — | Blank fits it automatically. (min 1, max 4) |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |

### `today-agenda`

What is left on today's calendar

| Param | Type | Default | Means |
|---|---|---|---|
| `calendar` | select | — | Which feed, or blank for all. Comma-separate for several. One of: a calendar named under `sources.calendars`. |
| `count` | number | `1` | 1 draws the hero layout; 2-3 stack as a list. (min 1, max 3) |
| `today` | bool | `false` | Only what is left today. |
| `hour24` | bool | `false` | 24-hour clock. |
| `lookahead_days` | number | `14` | How far ahead to look for events. (min 1, max 90) |
| `accent` | color | `amber` | One of: any palette colour or `#rrggbb`. |
| `time_color` | color | — | The time, drawn apart from the title; defaults to the accent. One of: any palette colour or `#rrggbb`. |
| `location` | bool | `true` | Show the location under the title. |
| `empty` | text | — | What to say when there is nothing. |

### `todos`

Open items from the reminders file

| Param | Type | Default | Means |
|---|---|---|---|
| `count` | number | `3` | How many rows. (min 1, max 4) |
| `style` | select | `list` | hero draws only the most pressing one, large. One of: `list`, `hero`. |
| `header` | bool | `true` | Show the title bar and count. |
| `title` | text | `REMINDERS` | Header text. |
| `accent` | color | `sky` | One of: any palette colour or `#rrggbb`. |
| `tag` | text | — | Only items with this tag. |

### `weather`

Current conditions

| Param | Type | Default | Means |
|---|---|---|---|
| `color` | color | `white` | Only used for mild temperatures; hot and cold pick their own. One of: any palette colour or `#rrggbb`. |
| `accent` | color | `amber` | One of: any palette colour or `#rrggbb`. |
| `precip` | bool | `true` | Chance of rain today, or the amount if it is falling now. |
| `aqi` | bool | `true` | US AQI, coloured by band: green good, red unhealthy. |
| `forecast` | number | `3` | Days of forecast on the right; 0 for none. (min 0, max 3) |
| `feels` | bool | `false` | Show 'feels like' when it differs. |
| `margin` | number | `8` | Blank kept at each edge, so the pane separates from its neighbours as the device pans past. (min 0, max 40) |
| `background` | color | `black` | One of: any palette colour or `#rrggbb`. |
